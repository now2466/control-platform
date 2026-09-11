import { PointerEvent, SyntheticEvent, useEffect, useMemo, useRef, useState } from 'react'
import { mapMetadata, MapMetadata } from './api'
import { canvasToWorld, centerViewOnWorld, isFreeOccupancyCell, MapInfo, staleAgeLabel, View, worldToCanvas, worldYawToCanvas } from './transforms'

type Point = { x: number; y: number }
export type Goal = Point & { yaw: number; frame_id: string }
type Robot = { robot_id: string; name: string; role: 'MASTER' | 'SLAVE'; pose?: { x: number; y: number; yaw: number } | null; pose_freshness?: string; trail?: Point[]; path?: Point[]; goal?: Goal | null; tf_valid?: boolean; tf_reason_code?: string | null; received_at?: string | null }
type Scan = { state: 'OK' | 'STALE' | 'ERROR' | 'UNSUPPORTED'; rays: { angle_rad: number; range_m: number }[] }
type Costmap = { name: 'local_costmap' | 'global_costmap'; state: 'OK' | 'STALE' | 'ERROR' | 'UNSUPPORTED'; cells: { x: number; y: number; occupied: boolean }[] }
type SensorLayers = { robot_id: string; scan: Scan; costmaps: Costmap[] }
type Layer = 'map' | 'scan' | 'local_costmap' | 'global_costmap'
const fallback: MapInfo = { width: 1, height: 1, resolution: 1, origin: { x: 0, y: 0, yaw: 0 } }

export default function MapPanel({ robots, selected, mapId, onSelect, onGoalChange }: { robots: Robot[]; selected: string; mapId?: string | null; onSelect: (id: string) => void; onGoalChange?: (goal: Goal | null) => void }) {
  const [metadata, setMetadata] = useState<MapMetadata | null>(null)
  const [error, setError] = useState('')
  const [view, setView] = useState<View>({ scale: 1, offsetX: 0, offsetY: 0 })
  const [following, setFollowing] = useState(false)
  const [preview, setPreview] = useState<Goal | null>(null)
  const [cellError, setCellError] = useState('')
  const [sensorLayers, setSensorLayers] = useState<SensorLayers | null>(null)
  const [sensorError, setSensorError] = useState('')
  const [layer, setLayer] = useState<Layer>('map')
  const occupancy = useRef<Uint8ClampedArray | null>(null)
  const start = useRef<Point | null>(null)
  const map: MapInfo = metadata ?? fallback
  const active = robots.find(robot => robot.robot_id === selected)
  const project = (point: Point) => worldToCanvas(point, map, view)

  useEffect(() => {
    if (!mapId) return
    let alive = true
    mapMetadata(mapId).then(value => { if (alive) { setMetadata(value); setView({ scale: 1, offsetX: 0, offsetY: 0 }); setError('') } }).catch(reason => alive && setError(reason.message))
    return () => { alive = false }
  }, [mapId])

  useEffect(() => {
    if (!selected) return
    let alive = true
    setSensorLayers(null); setSensorError('')
    fetch(`/api/v1/robots/${selected}/sensor-layers`, { credentials: 'include' })
      .then(response => response.ok ? response.json() as Promise<SensorLayers> : Promise.reject(new Error(`센서 상태 요청 실패 (${response.status})`)))
      .then(value => { if (alive && value.robot_id === selected) setSensorLayers(value) })
      .catch(reason => alive && setSensorError(reason.message))
    return () => { alive = false }
  }, [selected])

  useEffect(() => { if (following && active?.pose && metadata) setView(centerViewOnWorld(active.pose, metadata, view.scale)) }, [following, selected, active?.pose?.x, active?.pose?.y, metadata])

  const imageHref = useMemo(() => metadata ? `${metadata.data_url}?version=${encodeURIComponent(metadata.version)}` : '', [metadata])
  const selectedLayers = sensorLayers?.robot_id === selected ? sensorLayers : null
  const costmap = layer === 'scan' || layer === 'map' ? undefined : selectedLayers?.costmaps.find(item => item.name === layer)
  const layerState = layer === 'map' ? 'OK' : layer === 'scan' ? selectedLayers?.scan.state : costmap?.state
  const layerLabel = layer === 'map' ? '지도' : layer === 'scan' ? 'Scan' : layer === 'local_costmap' ? 'Local costmap' : 'Global costmap'
  const zoom = (factor: number) => setView(current => ({ ...current, scale: Math.max(.5, Math.min(4, current.scale * factor)) }))
  const pan = (x: number, y: number) => setView(current => ({ ...current, offsetX: current.offsetX + x, offsetY: current.offsetY + y }))
  const toCanvas = (event: PointerEvent<SVGSVGElement>) => { const rect = event.currentTarget.getBoundingClientRect(); const clientX = Number.isFinite(event.clientX) ? event.clientX : 0, clientY = Number.isFinite(event.clientY) ? event.clientY : 0; return { x: ((clientX - rect.left) / rect.width) * map.width, y: ((clientY - rect.top) / rect.height) * map.height } }
  const onPointerDown = (event: PointerEvent<SVGSVGElement>) => { start.current = toCanvas(event) }
  const onPointerUp = (event: PointerEvent<SVGSVGElement>) => {
    if (!metadata || !start.current) return
    const from = start.current, to = toCanvas(event); start.current = null; const world = canvasToWorld(from, map, view)
    if (occupancy.current && !isFreeOccupancyCell(world, map, occupancy.current)) { setCellError('점유 또는 미상 셀에는 목표를 지정할 수 없습니다.'); return }
    const direction = canvasToWorld(to, map, view), goal = { ...world, yaw: Math.atan2(direction.y - world.y, direction.x - world.x), frame_id: metadata.frame_id }
    setPreview(goal); onGoalChange?.(goal); setCellError('')
  }
  const loadOccupancy = (event: SyntheticEvent<SVGImageElement>) => {
    if (!metadata) return
    const image = event.currentTarget as unknown as SVGImageElement, raster = new Image(); raster.crossOrigin = 'anonymous'; raster.src = image.href.baseVal
    raster.onload = () => { const canvas = document.createElement('canvas'); canvas.width = metadata.width; canvas.height = metadata.height; const context = canvas.getContext('2d'); if (!context) return; context.drawImage(raster, 0, 0, metadata.width, metadata.height); occupancy.current = context.getImageData(0, 0, metadata.width, metadata.height).data.filter((_, index) => index % 4 === 0) }
  }

  return <section className="map-panel">
    <div className="map-toolbar"><h2>지도 · 로봇 위치</h2><div><button onClick={() => setView({ scale: 1, offsetX: 0, offsetY: 0 })}>전체 보기</button><button onClick={() => zoom(1.25)}>확대</button><button onClick={() => zoom(.8)}>축소</button><button onClick={() => pan(-10, 0)}>←</button><button onClick={() => pan(10, 0)}>→</button><button className={following ? 'active' : ''} onClick={() => setFollowing(value => !value)}>선택 따라보기</button></div></div>
    <div className="sensor-toolbar"><span>선택 로봇 센서</span>{(['map', 'scan', 'local_costmap', 'global_costmap'] as Layer[]).map(value => <button key={value} className={layer === value ? 'active' : ''} onClick={() => setLayer(value)}>{value === 'map' ? '지도' : value === 'scan' ? 'Scan' : value === 'local_costmap' ? 'Local costmap' : 'Global costmap'}</button>)}</div>
    {error && <div className="error">{error}</div>}
    <svg viewBox={`0 0 ${map.width} ${map.height}`} className="map" onPointerDown={onPointerDown} onPointerUp={onPointerUp}>
      {metadata ? <image href={imageHref} width={map.width} height={map.height} preserveAspectRatio="none" transform={`translate(${view.offsetX} ${view.offsetY}) scale(${view.scale})`} onLoad={loadOccupancy} /> : <rect width={map.width} height={map.height} fill="#18202b" />}
      {layer === 'scan' && active?.pose && selectedLayers?.scan.state === 'OK' && <g className="scan-layer">{selectedLayers.scan.rays.map((ray, index) => { const end = project({ x: active.pose!.x + Math.cos(active.pose!.yaw + ray.angle_rad) * ray.range_m, y: active.pose!.y + Math.sin(active.pose!.yaw + ray.angle_rad) * ray.range_m }), origin = project(active.pose!); return <line key={index} x1={origin.x} y1={origin.y} x2={end.x} y2={end.y} stroke="#62d7d1" strokeWidth=".7" /> })}</g>}
      {costmap?.state === 'OK' && <g className="costmap-layer">{costmap.cells.filter(cell => cell.occupied).map((cell, index) => { const point = project(cell); return <rect key={index} x={point.x - 2} y={point.y - 2} width="4" height="4" fill={layer === 'local_costmap' ? '#f87171' : '#c084fc'} opacity=".7" /> })}</g>}
      {robots.map(robot => robot.pose && <g key={robot.robot_id} onClick={event => { event.stopPropagation(); onSelect(robot.robot_id) }} className={selected === robot.robot_id ? 'selected-robot' : ''}>{robot.trail?.length ? <polyline points={robot.trail.map(point => { const q = project(point); return `${q.x},${q.y}` }).join(' ')} fill="none" stroke="#60718a" strokeWidth="1" /> : null}{robot.path?.length ? <polyline points={robot.path.map(point => { const q = project(point); return `${q.x},${q.y}` }).join(' ')} fill="none" stroke="#f0b35b" strokeDasharray="2 2" strokeWidth="1" /> : null}{robot.goal ? <circle cx={project(robot.goal).x} cy={project(robot.goal).y} r="4" fill="none" stroke="#f0b35b" /> : null}{(() => { const point = project(robot.pose!); const stale = robot.pose_freshness !== 'FRESH' || !robot.tf_valid; return <><circle cx={point.x} cy={point.y} r="4" fill={stale ? '#89919f' : robot.role === 'MASTER' ? '#3182ce' : '#ed8936'} /><line x1={point.x} y1={point.y} x2={point.x + Math.cos(worldYawToCanvas(robot.pose!.yaw, map)) * 9} y2={point.y + Math.sin(worldYawToCanvas(robot.pose!.yaw, map)) * 9} stroke="white" strokeWidth="1.5" /><text x={point.x + 5} y={point.y - 5} fill="white" fontSize="5">{robot.name}{stale ? ` · 위치 지연 ${staleAgeLabel(robot.received_at)}` : ''}</text></> })()}</g>)}
      {preview && <g className="goal-preview"><circle cx={project(preview).x} cy={project(preview).y} r="4" fill="none" stroke="#fff" /><line x1={project(preview).x} y1={project(preview).y} x2={project(preview).x + Math.cos(worldYawToCanvas(preview.yaw, map)) * 12} y2={project(preview).y + Math.sin(worldYawToCanvas(preview.yaw, map)) * 12} stroke="#fff" /></g>}
    </svg>
    {cellError && <p className="map-warning">{cellError}</p>}{sensorError && <p className="map-warning">센서 상세: {sensorError}</p>}
    {layer !== 'map' && <p className="map-note">{layerLabel} · {layerState === 'UNSUPPORTED' ? '지원하지 않음' : layerState === 'STALE' ? '데이터 지연' : layerState === 'ERROR' ? '오류' : layerState === 'OK' ? 'OK' : '상태 확인 중'}</p>}
    {robots.some(robot => !robot.tf_valid) && <p className="map-warning">TF 변환을 확인할 수 없어 편대 거리·방위각을 표시하지 않습니다.</p>}
    <p className="map-note">{selected ? `선택: ${selected}` : '로봇을 선택하세요'} · 지도 빈 공간을 클릭하고 드래그하면 목표 미리보기를 표시합니다. 명령은 전송하지 않습니다.</p>
  </section>
}
