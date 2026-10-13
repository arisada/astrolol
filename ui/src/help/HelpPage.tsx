// The user guide as a page of its own (/help/<topic>), for reading it in a separate tab.
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { LazyDocView as DocView } from './LazyDocView'
import { helpHref } from './HelpPanel'
import { INDEX_TOPIC } from './paths'

export function HelpPage() {
  const { topic = INDEX_TOPIC } = useParams()
  const { hash } = useLocation()
  const navigate = useNavigate()
  return (
    <div className="max-w-3xl mx-auto px-5 py-6">
      <DocView topic={topic} anchor={hash.slice(1)} hrefFor={helpHref}
        onNavigate={(tp, a) => navigate(helpHref(tp, a))} />
    </div>
  )
}
