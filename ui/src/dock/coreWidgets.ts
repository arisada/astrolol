// Dock widgets of the core pages. Plugins list theirs in their own ui/index.ts.
import { Compass } from 'lucide-react'
import i18n from '@/i18n'
import { registerDockWidget } from './registry'
import { MountPositionWidget } from './widgets/MountPosition'

registerDockWidget({
  id: 'mount.position',
  title: () => i18n.t('widget.position', { ns: 'mount' }),
  icon: Compass,
  route: '/mount',
  Component: MountPositionWidget,
})
