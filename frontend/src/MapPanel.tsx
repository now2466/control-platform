import { MouseEvent as ReactMouseEvent, PointerEvent, SyntheticEvent, useEffect, useMemo, useRef, useState } from 'react'
import { mapMetadata, MapMetadata } from './api'
import { canvasToWorld, centerViewOnWorld, isFreeOccupancyCell, MapInfo, staleAgeLabel, View, worldToCanvas, worldYawToCanvas } from './transforms'

type Point = { x: number; y: number }
export type Goal = Point & { yaw: number; frame_id: string }
type Robot = { robot_id: string; name: string; role: 'MASTER' | 'SLAVE'; pose?: { x: number; y: number; yaw: number } | null; pose_freshness?: string; trail?: Point[]; path?: Point[]; goal?: Goal | null; tf_valid?: boolean; tf_reason_code?: string | null; received_at?: string | null }
type ScanPoint = Point & { range_m: number }
type Scan = { state: 'OK' | 'STALE' | 'ERROR' | 'UNSUPPORTED'; frame_id?: string; points?: ScanPoint[]; rays?: { angle_rad: number; range_m: number }[]; point_count?: number; min_range_m?: number | null; reason_code?: string | null; received_at?: string | null }
type Costmap = { name: 'local_costmap' | 'global_costmap'; state: 'OK' | 'STALE' | 'ERROR' | 'UNSUPPORTED'; cells: { x: number; y: number; occupied: boolean }[] }
type SensorLayers = { robot_id: string; scan: Scan; costmaps: Costmap[] }
type Layer = 'map' | 'scan' | 'local_costmap' | 'global_costmap'
type SelectionMode = 'start' | 'destination'
const fallback: MapInfo = { width: 1, height: 1, resolution: 1, origin: { x: 0, y: 0, yaw: 0 } }

export default function MapPanel({ robots, selected, mapId, onSelect, onGoalChange, initialPose, onInitialPoseChange, onResetSelections, onNavigate, navigationReady = false, navigationBusy = false, navigationBlockers = [], onResetLocalization, localizationReady = false, localizationBusy = false, localizationBlockers = [], navigationStatus = '' }: { robots: Robot[]; selected: string; mapId?: string | null; onSelect: (id: string) => void; onGoalChange?: (goal: Goal | null) => void; initialPose?: Goal | null; onInitialPoseChange?: (pose: Goal | null) => void; onResetSelections?: () => void; onNavigate?: () => void; navigationReady?: boolean; navigationBusy?: boolean; navigationBlockers?: string[]; onResetLocalization?: () => void; localizationReady?: boolean; localizationBusy?: boolean; localizationBlockers?: string[]; navigationStatus?: string }) {
  const [metadata, setMetadata] = useState<MapMetadata | null>(null)
  const [error, setError] = useState('')
  const [view, setView] = useState<View>({ scale: 1, offsetX: 0, offsetY: 0 })
  const [following, setFollowing] = useState(false)
  const [preview, setPreview] = useState<Goal | null>(null)
  const [cellError, setCellError] = useState('')
  const [sensorLayers, setSensorLayers] = useState<SensorLayers | null>(null)
  const [sensorError, setSensorError] = useState('')
  const [layer, setLayer] = useState<Layer>('map')
  const [selectionMode, setSelectionMode] = useState<SelectionMode>('destination')
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
    let timer: ReturnType<typeof setTimeout> | undefined
    setSensorLayers(null); setSensorError('')
    const refresh = () => fetch(`/api/v1/robots/${selected}/sensor-layers`, { credentials: 'include' })
      .then(response => response.ok ? response.json() as Promise<SensorLayers> : Promise.reject(new Error(`센서 상태 요청 실패 (${response.status})`)))
      .then(value => { if (alive && value.robot_id === selected) { setSensorLayers(value); setSensorError('') } })
      .catch(reason => alive && setSensorError(reason.message))
      .finally(() => { if (alive && layer === 'scan') timer = setTimeout(refresh, 200) })
    void refresh()
    return () => { alive = false; if (timer) clearTimeout(timer) }
  }, [selected, layer])

  useEffect(() => { if (following && active?.pose && metadata) setView(centerViewOnWorld(active.pose, metadata, view.scale)) }, [following, selected, active?.pose?.x, active?.pose?.y, metadata])

  const imageHref = useMemo(() => metadata ? `${metadata.data_url}?version=${encodeURIComponent(metadata.version)}` : '', [metadata])
  const selectedLayers = sensorLayers?.robot_id === selected ? sensorLayers : null
  const scanPoints = selectedLayers?.scan.points ?? (active?.pose ? (selectedLayers?.scan.rays ?? []).map(ray => ({ x: active.pose!.x + Math.cos(active.pose!.yaw + ray.angle_rad) * ray.range_m, y: active.pose!.y + Math.sin(active.pose!.yaw + ray.angle_rad) * ray.range_m, range_m: ray.range_m })) : [])
  const costmap = layer === 'scan' || layer === 'map' ? undefined : selectedLayers?.costmaps.find(item => item.name === layer)
  const layerState = layer === 'map' ? 'OK' : layer === 'scan' ? selectedLayers?.scan.state : costmap?.state
  const layerLabel = layer === 'map' ? '지도' : layer === 'scan' ? 'Scan' : layer === 'local_costmap' ? 'Local costmap' : 'Global costmap'
  const navigationReasons = preview ? navigationBlockers : [...navigationBlockers, '도착점을 지정하지 않았습니다.']
  const canResetLocalization = Boolean(localizationReady && initialPose && onResetLocalization && !localizationBusy)
  const canNavigate = Boolean(navigationReady && initialPose && preview && onNavigate && !navigationBusy)
  const zoom = (factor: number) => setView(current => ({ ...current, scale: Math.max(.5, Math.min(4, current.scale * factor)) }))
  const pan = (x: number, y: number) => setView(current => ({ ...current, offsetX: current.offsetX + x, offsetY: current.offsetY + y }))
  const toCanvas = (event: { currentTarget: SVGElement; clientX: number; clientY: number }) => { const svg = event.currentTarget.ownerSVGElement ?? event.currentTarget as SVGSVGElement, rect = svg.getBoundingClientRect(); const clientX = Number.isFinite(event.clientX) ? event.clientX : 0, clientY = Number.isFinite(event.clientY) ? event.clientY : 0; return { x: ((clientX - rect.left) / rect.width) * map.width, y: ((clientY - rect.top) / rect.height) * map.height } }
  const onPointerDown = (event: PointerEvent<SVGElement>) => { if (event.button === 0) start.current = toCanvas(event) }
  const selectPoint = (event: { currentTarget: SVGElement; clientX: number; clientY: number }) => {
    if (!metadata) return
    const to = toCanvas(event), from = start.current ?? to; start.current = null; const world = canvasToWorld(from, map, view)
    if (occupancy.current && !isFreeOccupancyCell(world, map, occupancy.current)) { setCellError('점유 또는 미상 셀에는 목표를 지정할 수 없습니다.'); return }
    const direction = canvasToWorld(to, map, view), goal = { ...world, yaw: Math.atan2(direction.y - world.y, direction.x - world.x), frame_id: metadata.frame_id }
    if (selectionMode === 'start') onInitialPoseChange?.(goal)
    else { setPreview(goal); onGoalChange?.(goal) }
    setCellError('')
  }
  const onClick = (event: ReactMouseEvent<SVGRectElement>) => { selectPoint(event) }
  const loadOccupancy = (event: SyntheticEvent<SVGImageElement>) => {
    if (!metadata) return
    const image = event.currentTarget as unknown as SVGImageElement, raster = new Image(); raster.crossOrigin = 'anonymous'; raster.src = image.href.baseVal
    raster.onload = () => { const canvas = document.createElement('canvas'); canvas.width = metadata.width; canvas.height = metadata.height; const context = canvas.getContext('2d'); if (!context) return; context.drawImage(raster, 0, 0, metadata.width, metadata.height); occupancy.current = context.getImageData(0, 0, metadata.width, metadata.height).data.filter((_, index) => index % 4 === 0) }
  }

  return <section className="map-panel">
    <div className="map-toolbar"><h2>지도 · 로봇 위치</h2><div><button className={selectionMode === 'start' ? 'active' : ''} onClick={() => setSelectionMode('start')}>시작점 설정</button><button className={selectionMode === 'destination' ? 'active' : ''} onClick={() => setSelectionMode('destination')}>도착점 설정</button><button onClick={() => { setPreview(null); onGoalChange?.(null); onInitialPoseChange?.(null); onResetSelections?.() }}>설정 초기화</button><button disabled={!canResetLocalization} title={!canResetLocalization ? localizationBlockers.join(' ') : undefined} onClick={onResetLocalization}>{localizationBusy ? '위치 재설정 중…' : '위치 재설정(AMCL)'}</button><button disabled={!canNavigate} title={!canNavigate ? navigationReasons.join(' ') : undefined} onClick={onNavigate}>{navigationBusy ? '이동 요청 중…' : '시작점에서 도착점으로 이동'}</button><button onClick={() => setView({ scale: 1, offsetX: 0, offsetY: 0 })}>전체 보기</button><button onClick={() => zoom(1.25)}>확대</button><button onClick={() => zoom(.8)}>축소</button><button onClick={() => pan(-10, 0)}>←</button><button onClick={() => pan(10, 0)}>→</button><button className={following ? 'active' : ''} onClick={() => setFollowing(value => !value)}>선택 따라보기</button></div></div>
    <div className="sensor-toolbar"><span>선택 로봇 센서</span>{(['map', 'scan', 'local_costmap', 'global_costmap'] as Layer[]).map(value => <button key={value} className={layer === value ? 'active' : ''} onClick={() => setLayer(value)}>{value === 'map' ? '지도' : value === 'scan' ? 'Scan' : value === 'local_costmap' ? 'Local costmap' : 'Global costmap'}</button>)}</div>
    {error && <div className="error">{error}</div>}
    <svg viewBox={`0 0 ${map.width} ${map.height}`} className="map">
      {metadata ? <image href={imageHref} width={map.width} height={map.height} preserveAspectRatio="none" transform={`translate(${view.offsetX} ${view.offsetY}) scale(${view.scale})`} onLoad={loadOccupancy} /> : <rect width={map.width} height={map.height} fill="#18202b" />}
      {metadata && <rect className="map-input-layer" width={map.width} height={map.height} fill="transparent" pointerEvents="all" onPointerDown={onPointerDown} onClick={onClick} />}
      {layer === 'scan' && selectedLayers?.scan.state === 'OK' && <g className="scan-layer" pointerEvents="none">{scanPoints.map((hit, index) => { const point = project(hit); return <circle key={index} cx={point.x} cy={point.y} r={hit.range_m < .2 ? 2.2 : hit.range_m < .5 ? 1.7 : 1.25} fill={hit.range_m < .2 ? '#ff334f' : hit.range_m < .5 ? '#ffb020' : '#19d3c5'} stroke={hit.range_m < .2 ? '#7f0014' : 'none'} strokeWidth=".5" opacity=".9" /> })}</g>}
      {costmap?.state === 'OK' && <g className="costmap-layer">{costmap.cells.filter(cell => cell.occupied).map((cell, index) => { const point = project(cell); return <rect key={index} x={point.x - 2} y={point.y - 2} width="4" height="4" fill={layer === 'local_costmap' ? '#f87171' : '#c084fc'} opacity=".7" /> })}</g>}
      {robots.map(robot => robot.pose && <g key={robot.robot_id} onClick={event => { event.stopPropagation(); onSelect(robot.robot_id) }} className={selected === robot.robot_id ? 'selected-robot' : ''}>{robot.trail?.length ? <polyline points={robot.trail.map(point => { const q = project(point); return `${q.x},${q.y}` }).join(' ')} fill="none" stroke="#60718a" strokeWidth="1" /> : null}{robot.path?.length ? <polyline points={robot.path.map(point => { const q = project(point); return `${q.x},${q.y}` }).join(' ')} fill="none" stroke="#f0b35b" strokeDasharray="2 2" strokeWidth="1" /> : null}{robot.goal ? <circle cx={project(robot.goal).x} cy={project(robot.goal).y} r="4" fill="none" stroke="#f0b35b" /> : null}{(() => { const point = project(robot.pose!); const stale = robot.pose_freshness !== 'FRESH' || !robot.tf_valid; return <><circle cx={point.x} cy={point.y} r="4" fill={stale ? '#89919f' : robot.role === 'MASTER' ? '#3182ce' : '#ed8936'} /><line x1={point.x} y1={point.y} x2={point.x + Math.cos(worldYawToCanvas(robot.pose!.yaw, map)) * 9} y2={point.y + Math.sin(worldYawToCanvas(robot.pose!.yaw, map)) * 9} stroke="white" strokeWidth="1.5" /><text x={point.x + 5} y={point.y - 5} fill="white" fontSize="5">{robot.name}{stale ? ` · 위치 지연 ${staleAgeLabel(robot.received_at)}` : ''}</text></> })()}</g>)}
      {initialPose && <g className="initial-pose-marker"><circle cx={project(initialPose).x} cy={project(initialPose).y} r="5" fill="none" stroke="#9de5bc" strokeWidth="1.5" /><line x1={project(initialPose).x} y1={project(initialPose).y} x2={project(initialPose).x + Math.cos(worldYawToCanvas(initialPose.yaw, map)) * 13} y2={project(initialPose).y + Math.sin(worldYawToCanvas(initialPose.yaw, map)) * 13} stroke="#9de5bc" strokeWidth="2" /><text x={project(initialPose).x + 6} y={project(initialPose).y + 5} fill="#9de5bc" fontSize="5">시작점</text></g>}
      {preview && <g className="goal-preview"><circle cx={project(preview).x} cy={project(preview).y} r="5" fill="#ff8a3d" fillOpacity=".25" stroke="#ff5a36" strokeWidth="2" /><line x1={project(preview).x} y1={project(preview).y} x2={project(preview).x + Math.cos(worldYawToCanvas(preview.yaw, map)) * 12} y2={project(preview).y + Math.sin(worldYawToCanvas(preview.yaw, map)) * 12} stroke="#ff5a36" strokeWidth="2.5" /><text x={project(preview).x + 6} y={project(preview).y + 5} fill="#d9362b" stroke="white" strokeWidth=".5" paintOrder="stroke" fontSize="5">도착점</text></g>}
    </svg>
    {cellError && <p className="map-warning">{cellError}</p>}{sensorError && <p className="map-warning">센서 상세: {sensorError}</p>}
    {layer !== 'map' && <p className="map-note">{layerLabel} · {layerState === 'UNSUPPORTED' ? '지원하지 않음' : layerState === 'STALE' ? '데이터 지연' : layerState === 'ERROR' ? `오류 (${selectedLayers?.scan.reason_code ?? '원인 확인 필요'})` : layerState === 'OK' ? 'OK' : '상태 확인 중'}{layer === 'scan' && layerState === 'OK' ? ` · 점 ${selectedLayers?.scan.point_count ?? scanPoints.length}개 · 최근접 ${selectedLayers?.scan.min_range_m?.toFixed(3) ?? '-'} m · 5Hz 갱신` : ''}</p>}
    {layer === 'scan' && <p className="map-note">Scan 색상: <span className="scan-near">빨강 0.2m 미만</span> · <span className="scan-mid">주황 0.5m 미만</span> · 청록 그 이상</p>}
    {robots.some(robot => !robot.tf_valid) && <p className="map-warning">TF 변환을 확인할 수 없어 편대 거리·방위각을 표시하지 않습니다.</p>}
    {!localizationReady && localizationBlockers.length > 0 && <p className="map-warning">위치 재설정 불가: {localizationBlockers.join(' ')}</p>}
    {!canNavigate && navigationReasons.length > 0 && <p className="map-warning">이동 불가: {navigationReasons.join(' ')}</p>}
    <p className="map-note">{selected ? `선택: ${selected}` : '로봇을 선택하세요'} · {selectionMode === 'start' ? '지도에서 시작 위치를 클릭하고 드래그하세요.' : '지도에서 도착 위치를 클릭하고 드래그하세요. 목표 미리보기를 표시합니다.'} {canNavigate ? '두 점과 AMCL 위치를 확인한 뒤 이동 버튼으로 주행을 시작하세요.' : '위 안내에서 준비되지 않은 조건을 확인하세요.'} {navigationStatus}</p>
  </section>
}
