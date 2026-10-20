import React, { useMemo, useState } from 'react'

export interface Column<T> {
  key: string
  label: string
  sort?: (row: T) => number | string | null | undefined
  render?: (row: T) => React.ReactNode
  align?: 'left' | 'right'
  title?: string
}

interface Props<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  initialSortKey?: string
  initialDesc?: boolean
  expand?: (row: T) => React.ReactNode
  emptyText?: string
}

export default function SortTable<T>({
  columns,
  rows,
  rowKey,
  initialSortKey,
  initialDesc = false,
  expand,
  emptyText = 'No rows.',
}: Props<T>) {
  const [sortKey, setSortKey] = useState<string>(initialSortKey ?? '')
  const [desc, setDesc] = useState<boolean>(initialDesc)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const sorted = useMemo(() => {
    const column = columns.find((c) => c.key === sortKey)
    if (!column?.sort) return rows
    const copy = [...rows]
    copy.sort((a, b) => {
      const va = column.sort!(a)
      const vb = column.sort!(b)
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      if (typeof va === 'number' && typeof vb === 'number') return va - vb
      return String(va).localeCompare(String(vb))
    })
    return desc ? copy.reverse() : copy
  }, [rows, columns, sortKey, desc])

  const toggleSort = (key: string) => {
    if (key === sortKey) {
      setDesc(!desc)
    } else {
      setSortKey(key)
      setDesc(false)
    }
  }

  const toggleExpand = (key: string) => {
    setExpanded((previous) => {
      const next = new Set(previous)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (!rows.length) {
    return <div className="muted" style={{ padding: '8px 0' }}>{emptyText}</div>
  }

  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {expand && <th style={{ width: 28 }} />}
            {columns.map((column) => (
              <th
                key={column.key}
                className={column.align === 'right' ? 'num' : ''}
                title={column.title}
                style={{ cursor: column.sort ? 'pointer' : 'default' }}
                onClick={() => column.sort && toggleSort(column.key)}
              >
                {column.label}
                {sortKey === column.key ? (desc ? ' ▾' : ' ▴') : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const key = rowKey(row)
            const isOpen = expanded.has(key)
            return (
              <React.Fragment key={key}>
                <tr className={isOpen ? 'expanded' : ''}>
                  {expand && (
                    <td className="expander" onClick={() => toggleExpand(key)}>
                      {isOpen ? '▾' : '▸'}
                    </td>
                  )}
                  {columns.map((column) => (
                    <td key={column.key} className={column.align === 'right' ? 'num' : ''}>
                      {column.render ? column.render(row) : null}
                    </td>
                  ))}
                </tr>
                {isOpen && expand && (
                  <tr className="expand-row">
                    <td colSpan={columns.length + 1}>{expand(row)}</td>
                  </tr>
                )}
              </React.Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
