export function Card({ title, action, children, className = '' }: {
  title?: React.ReactNode
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  const hasHeader = title != null || action != null
  return (
    <div className={`border border-surface-border rounded-lg ${className}`}>
      {hasHeader && (
        <div className="flex items-center justify-between">
          {title != null && (
            <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider">{title}</h3>
          )}
          {action}
        </div>
      )}
      {children}
    </div>
  )
}

export function SidebarSection({ title, action, children }: {
  title: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="border-b border-surface-border px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">{title}</p>
        {action}
      </div>
      {children}
    </div>
  )
}
