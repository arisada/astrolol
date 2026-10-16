import { Monitor } from 'lucide-react'
import { SystemPage } from './SystemPage'
import { SystemChip } from './SystemChip'
import i18n from '@/i18n'
import { SystemHealthWidget } from './SystemWidgets'

export default {
  icon: Monitor,
  label: 'System',
  Component: SystemPage,
  StatusChip: SystemChip,
  widgets: [
    { id: 'health', title: () => i18n.t('widget.health', { ns: 'system' }), Component: SystemHealthWidget },
  ],
}
