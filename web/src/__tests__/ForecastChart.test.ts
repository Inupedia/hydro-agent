import { mount, flushPromises } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import ForecastChart from '../components/ForecastChart.vue'
const mocks=vi.hoisted(()=>({setOption:vi.fn(),resize:vi.fn(),dispose:vi.fn(),init:vi.fn()}))
vi.mock('echarts',()=>({init:mocks.init}))
it('initializes when data arrives and resizes with its container',async()=>{
 let resize:()=>void=()=>{}
 const disconnect=vi.fn()
 vi.stubGlobal('ResizeObserver',class {constructor(cb:()=>void){resize=cb}observe(){}disconnect=disconnect})
 mocks.init.mockReturnValue(mocks)
 const wrapper=mount(ForecastChart,{props:{forecasts:[]}})
 await flushPromises()
 expect(mocks.init).not.toHaveBeenCalled()
 await wrapper.setProps({forecasts:[{issue_time:'2020-01-01',lead_values:{1:10,2:12,3:13}}]})
 await flushPromises()
 expect(mocks.init).toHaveBeenCalledTimes(1)
 expect(mocks.setOption).toHaveBeenCalled()
 resize();expect(mocks.resize).toHaveBeenCalled()
 wrapper.unmount();expect(disconnect).toHaveBeenCalled();vi.unstubAllGlobals()
})
