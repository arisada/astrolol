// Dock widgets of the core pages. Plugins list theirs in their own ui/index.ts.
import { AlertTriangle, Compass, Focus, Gauge, Globe, Move, Palette } from 'lucide-react'
import i18n from '@/i18n'
import { registerDockWidget } from './registry'
import { FilterWheelWidget } from './widgets/FilterWheel'
import { FocuserWidget } from './widgets/Focuser'
import { MountHorizonWidget } from './widgets/MountHorizon'
import { MountNudgeWidget } from './widgets/MountNudge'
import { MountPositionWidget } from './widgets/MountPosition'
import { MountStateWidget } from './widgets/MountState'
import { WarningsWidget } from './widgets/Warnings'

const title = (key: string, ns: string) => () => i18n.t(key, { ns })

registerDockWidget({ id: 'mount.position', perDevice: 'mount', title: title('widget.position', 'mount'), icon: Compass, route: '/mount', Component: MountPositionWidget })
registerDockWidget({ id: 'mount.horizon', perDevice: 'mount', title: title('widget.horizon', 'mount'), icon: Globe, route: '/mount', Component: MountHorizonWidget })
registerDockWidget({ id: 'mount.state', perDevice: 'mount', title: title('widget.stateTitle', 'mount'), icon: Gauge, route: '/mount', Component: MountStateWidget })
registerDockWidget({ id: 'mount.nudge', perDevice: 'mount', title: title('widget.nudge', 'mount'), icon: Move, route: '/mount', Component: MountNudgeWidget })
registerDockWidget({ id: 'focuser.position', perDevice: 'focuser', title: title('widget.focuser', 'imaging'), icon: Focus, route: '/imaging', Component: FocuserWidget })
registerDockWidget({ id: 'filter_wheel.current', perDevice: 'filter_wheel', title: title('widget.filterWheel', 'imaging'), icon: Palette, route: '/imaging', Component: FilterWheelWidget })
registerDockWidget({ id: 'logs.warnings', title: title('widget.warnings', 'logs'), icon: AlertTriangle, route: '/logs', Component: WarningsWidget })
