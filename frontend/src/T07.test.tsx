import { render, screen, fireEvent, act, cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import MissionPanel from './MissionPanel'
const goal=(x:number)=>({x,y:x,yaw:0,frame_id:'map' as const})
beforeEach(()=>{
  cleanup(); vi.stubGlobal('crypto',{randomUUID:()=>`id`})
  vi.stubGlobal('fetch',vi.fn().mockImplementation((input,init)=>{
    if (String(input).endsWith('/missions') && (!init?.method || init.method === 'GET')) return Promise.resolve(new Response(JSON.stringify({items:[]})))
    return Promise.resolve(new Response(JSON.stringify({mission_id:'m1',state:'DRAFT',waypoints:[goal(1),goal(2),goal(3)]}),{status:201}))
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
test('adds three map waypoints and supports reorder/delete',async()=>{const view=render(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'READY'}} goal={goal(1)} onError={()=>{}}/>);await act(async()=>{});view.rerender(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'READY'}} goal={goal(2)} onError={()=>{}}/>);await act(async()=>{});view.rerender(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'READY'}} goal={goal(3)} onError={()=>{}}/>);await act(async()=>{});expect(screen.getByTestId('mission-progress')).toHaveTextContent('waypoint 3개');fireEvent.click(screen.getAllByText('아래')[0]);fireEvent.click(screen.getAllByText('삭제')[1]);expect(screen.getByTestId('mission-progress')).toHaveTextContent('waypoint 2개')})
test('create sends repeat_count and all waypoint coordinates',async()=>{const view=render(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'READY'}} goal={goal(1)} onError={()=>{}}/>);view.rerender(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'READY'}} goal={goal(2)} onError={()=>{}}/>);view.rerender(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'READY'}} goal={goal(3)} onError={()=>{}}/>);fireEvent.change(screen.getByLabelText(/반복/),{target:{value:'2'}});fireEvent.click(screen.getByText('임무 생성'));await act(async()=>{});const call=vi.mocked(fetch).mock.calls.find(([,init])=>init?.method==='POST')!;const body=JSON.parse(call[1]!.body as string);expect(body.repeat_count).toBe(2);expect(body.waypoints).toHaveLength(3)})

test('save uses PATCH with mission version and edited waypoints',async()=>{render(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'READY'}} goal={goal(1)} onError={()=>{}}/>);fireEvent.click(screen.getByText('임무 생성'));await act(async()=>{});fireEvent.click(screen.getByText('저장'));await act(async()=>{});const call=vi.mocked(fetch).mock.calls.find(([,init])=>init?.method==='PATCH')!;const request=call[1] as RequestInit;expect(request.method).toBe('PATCH');expect(JSON.parse(request.body as string)).toMatchObject({version:1,waypoints:[goal(1)]})})

test('mission action polls the 202 command before refreshing mission state',async()=>{vi.mocked(fetch).mockImplementation(async input=>{const path=String(input);if(path.endsWith('/missions'))return new Response(JSON.stringify({mission_id:'m1',state:'DRAFT',version:1}),{status:201});if(path.includes('/actions'))return new Response(JSON.stringify({command_id:'c1'}),{status:202});if(path.includes('/commands/'))return new Response(JSON.stringify({command_id:'c1',state:'SUCCEEDED'}));return new Response(JSON.stringify({mission_id:'m1',state:'READY',version:1}))});render(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'READY'}} goal={goal(1)} onError={()=>{}}/>);fireEvent.click(screen.getByText('임무 생성'));await act(async()=>{});fireEvent.click(screen.getByText('검증'));await act(async()=>{});expect(screen.getByText(/임무 · READY/)).toBeInTheDocument();expect(vi.mocked(fetch).mock.calls.some(([path])=>String(path).includes('/commands/c1'))).toBe(true)})

test('start remains gated until formation is READY',()=>{render(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'PAUSED'}} goal={goal(1)} onError={()=>{}}/>);expect(screen.getByText('시작')).toBeDisabled();expect(screen.getByText(/READY 편대/)).toBeInTheDocument()})

test('progress renders current waypoint, lap and distance from mission snapshot',async()=>{vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({mission_id:'m1',state:'RUNNING',waypoint_index:1,lap_index:1,repeat_count:2,progress_distance_m:3.5,waypoints:[goal(1),goal(2),goal(3)]}),{status:201}));render(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'READY'}} goal={goal(1)} onError={()=>{}}/>);fireEvent.click(screen.getByText('임무 생성'));await act(async()=>{});expect(screen.getByTestId('mission-progress')).toHaveTextContent('현재 2/3 · lap 2/2 · 진행 3.5m')})

test('save uses the server version and reports 409 without claiming success',async()=>{const error=vi.fn();vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({mission_id:'m1',state:'READY',version:7}),{status:201})).mockResolvedValueOnce(new Response(JSON.stringify({error:{message:'version conflict'}}),{status:409}));render(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'READY'}} goal={goal(1)} onError={error}/>);fireEvent.click(screen.getByText('임무 생성'));await act(async()=>{});fireEvent.click(screen.getByText('저장'));await act(async()=>{});const request=vi.mocked(fetch).mock.calls[1][1] as RequestInit;expect(JSON.parse(request.body as string).version).toBe(7);expect(error).toHaveBeenCalledWith('version conflict')})

test('paused mission exposes resume and keeps start disabled',async()=>{vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({mission_id:'m1',state:'PAUSED',version:1}),{status:201}));render(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'READY'}} goal={goal(1)} onError={()=>{}}/>);fireEvent.click(screen.getByText('임무 생성'));await act(async()=>{});expect(screen.getByText('시작')).toBeDisabled();expect(screen.getByText('재개')).toBeEnabled()})

test('deleting the last waypoint disables create and save', () => {
  render(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'READY'}} goal={goal(1)} onError={()=>{}} />)
  fireEvent.click(screen.getByText('삭제'))
  expect(screen.getByText('임무 생성')).toBeDisabled()
  expect(screen.getByText('저장')).toBeDisabled()
})

test('loads a paused mission from the list while paused formation stays resumable without auto action',async()=>{
  const saved = { mission_id:'saved', name:'복구 임무', state:'PAUSED', version:4, repeat_count:2, waypoint_index:1, lap_index:1, progress_distance_m:8, waypoints:[goal(1),goal(2)] }
  const calls: string[] = []
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    calls.push(String(input))
    if (String(input).endsWith('/missions') && !init?.method) return new Response(JSON.stringify({items:[saved]}))
    return new Response(JSON.stringify(saved), {status:200})
  })
  render(<MissionPanel lease="l" mapId="mock_lab" formation={{state:'PAUSED'}} goal={null} onError={() => {}} />)
  fireEvent.click(screen.getByText('임무 목록 새로고침'))
  await act(async () => {})
  fireEvent.change(screen.getByLabelText('저장된 임무'), {target:{value:'saved'}})
  expect(screen.getByText('재개')).toBeEnabled()
  expect(screen.getByTestId('mission-progress')).toHaveTextContent('waypoint 2개')
  expect(screen.getByTestId('mission-progress')).toHaveTextContent('현재 2/2 · lap 2/2 · 진행 8m')
  expect(calls.some(path => path.includes('/actions'))).toBe(false)
})
