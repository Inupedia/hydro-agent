import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import GlassSelect from '../components/GlassSelect.vue'

describe('GlassSelect', () => {
  it('opens a glass menu and emits the chosen value', async () => {
    const wrapper = mount(GlassSelect, {
      props: {
        modelValue: 'yaogu',
        ariaLabel: '研究流域',
        options: [
          { value: 'yaogu', label: '腰古' },
          { value: 'usgs_02472000', label: 'Leaf River' },
        ],
      },
      attachTo: document.body,
    })
    expect(wrapper.text()).toContain('腰古')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    const option = document.body.querySelector('[data-value="usgs_02472000"]') as HTMLElement | null
    expect(option).not.toBeNull()
    option?.click()
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['usgs_02472000'])
    wrapper.unmount()
  })
})
