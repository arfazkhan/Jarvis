import { useState } from 'react'
import {
  DndContext, closestCenter, PointerSensor, useSensor, useSensors,
} from '@dnd-kit/core'
import {
  SortableContext, useSortable, verticalListSortingStrategy, arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  GripVertical, Plus, Trash2, Copy, X, Check, Hash, ToggleLeft, FileText,
  Save, Eye, Camera, TriangleAlert,
} from 'lucide-react'
import { Input, Select } from './Issues'
import { api } from '../api/client'

// No-code checklist builder — drag to reorder, click a type to add, live preview.
// Reference shape = the One Anthem templates (clone-to-start supported).
let _uid = 0
const uid = () => `n${++_uid}`
const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 36)

const TYPES = [
  { k: 'tick', label: 'OK / Issue', icon: Check, hint: 'Pass-fail check' },
  { k: 'reading', label: 'Reading', icon: Hash, hint: 'A number + unit' },
  { k: 'state', label: 'State', icon: ToggleLeft, hint: 'Pick one option' },
  { k: 'note', label: 'Note', icon: FileText, hint: 'Free text' },
]

function newItem(kind = 'tick') {
  return {
    id: uid(), origId: '', label: '', kind,
    unit: '', options: kind === 'state' ? 'OK, ISSUE' : '', alert: kind === 'state' ? 'ISSUE' : '', asset: '',
  }
}
function newSection() { return { id: uid(), name: 'New section', items: [newItem()] } }

function fromTemplate(t, { clone } = {}) {
  return {
    template_id: clone ? '' : (t.template_id || ''),
    name: clone ? `${t.name} (copy)` : (t.name || ''),
    cadence: t.cadence || 'daily',
    timing: t.timing || '',
    sections: (t.sections || []).map((s) => ({
      id: uid(), name: s.name || '',
      items: (s.items || []).map((it) => ({
        id: uid(), origId: clone ? '' : (it.item_id || ''), label: it.label || '', kind: it.kind || 'tick',
        unit: it.unit || '', options: (it.options || []).join(', '),
        alert: (it.alert_states || []).join(', '), asset: it.asset || '',
      })),
    })),
  }
}

export default function ChecklistBuilder({ building, initial, onSaved, onCancel }) {
  const start = initial ? fromTemplate(initial, { clone: initial._clone }) : {
    template_id: '', name: '', cadence: 'daily', timing: '', sections: [newSection()],
  }
  const [meta, setMeta] = useState({ template_id: start.template_id, name: start.name, cadence: start.cadence, timing: start.timing })
  const [sections, setSections] = useState(start.sections)
  const [busy, setBusy] = useState(false)
  const [showPreview, setShowPreview] = useState(true)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

  const setSection = (id, patch) => setSections((ss) => ss.map((s) => (s.id === id ? { ...s, ...patch } : s)))
  const setItem = (sid, iid, patch) =>
    setSection(sid, { items: sections.find((s) => s.id === sid).items.map((it) => (it.id === iid ? { ...it, ...patch } : it)) })

  function onDragEnd({ active, over }) {
    if (!over || active.id === over.id) return
    const si = sections.findIndex((s) => s.id === active.id)
    if (si >= 0) { // section reorder
      const oi = sections.findIndex((s) => s.id === over.id)
      if (oi >= 0) setSections(arrayMove(sections, si, oi))
      return
    }
    for (const s of sections) { // item reorder within its section
      const ai = s.items.findIndex((it) => it.id === active.id)
      if (ai >= 0) {
        const oi = s.items.findIndex((it) => it.id === over.id)
        if (oi >= 0) setSection(s.id, { items: arrayMove(s.items, ai, oi) })
        return
      }
    }
  }

  async function save() {
    const tid = (meta.template_id || slug(meta.name).toUpperCase().replace(/_/g, '-')).trim()
    if (!meta.name.trim() || !tid) return alert('Name is required')
    const seen = new Set()
    const outSections = sections
      .filter((s) => s.name.trim() && s.items.some((it) => it.label.trim()))
      .map((s) => ({
        name: s.name.trim(),
        items: s.items.filter((it) => it.label.trim()).map((it) => {
          let id = it.origId || slug(it.label) || 'item'
          while (seen.has(id)) id += '_x'
          seen.add(id)
          const o = { item_id: id, label: it.label.trim(), kind: it.kind }
          if (it.kind === 'reading' && it.unit) o.unit = it.unit.trim()
          if (it.kind === 'state') {
            o.options = it.options.split(',').map((x) => x.trim()).filter(Boolean)
            if (it.alert) o.alert_states = it.alert.split(',').map((x) => x.trim()).filter(Boolean)
          }
          if (it.asset) o.asset = it.asset.trim()
          return o
        }),
      }))
    if (!outSections.length || !seen.size) return alert('Add at least one section with one named check')
    setBusy(true)
    try {
      await api.saveTemplate({ building, template: { template_id: tid, name: meta.name.trim(), cadence: meta.cadence, timing: meta.timing.trim(), signoff_roles: ['technician', 'supervisor'], sections: outSections } })
      onSaved()
    } catch (e) { alert(e.message) } finally { setBusy(false) }
  }

  return (
    <div>
      {/* sticky header */}
      <div className="flex items-center justify-between mb-5">
        <div className="text-xl font-serif text-text">{initial && !initial._clone ? 'Edit checklist' : 'New checklist'}</div>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowPreview((v) => !v)} className="flex items-center gap-1.5 text-sm border border-border rounded-lg px-3 py-2 text-text-dim hover:border-gold/40">
            <Eye className="w-4 h-4" /> {showPreview ? 'Hide preview' : 'Preview'}
          </button>
          <button onClick={onCancel} className="text-sm text-text-faint flex items-center gap-1 px-2"><X className="w-4 h-4" /> Cancel</button>
          <button disabled={busy} onClick={save} className="flex items-center gap-1.5 bg-primary text-white rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50">
            <Save className="w-4 h-4" /> Save
          </button>
        </div>
      </div>

      {/* meta */}
      <div className="grid grid-cols-4 gap-3 bg-surface border border-border rounded-xl p-4 mb-5">
        <Field label="Name"><Input value={meta.name} onChange={(v) => setMeta({ ...meta, name: v })} /></Field>
        <Field label="ID (auto if blank)"><Input value={meta.template_id} onChange={(v) => setMeta({ ...meta, template_id: v })} /></Field>
        <Field label="Cadence"><Select value={meta.cadence} options={['daily', 'weekly', 'monthly', 'quarterly']} onChange={(v) => setMeta({ ...meta, cadence: v })} /></Field>
        <Field label="Timing (e.g. 08:00 AM – 04:15 PM)"><Input value={meta.timing} onChange={(v) => setMeta({ ...meta, timing: v })} /></Field>
      </div>

      <div className={showPreview ? 'grid grid-cols-[1fr_360px] gap-6 items-start' : ''}>
        {/* canvas */}
        <div>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={sections.map((s) => s.id)} strategy={verticalListSortingStrategy}>
              {sections.map((s) => (
                <SortableSection key={s.id} section={s}
                  onName={(v) => setSection(s.id, { name: v })}
                  onDelete={() => setSections((ss) => ss.filter((x) => x.id !== s.id))}
                  onDuplicate={() => setSections((ss) => { const i = ss.findIndex((x) => x.id === s.id); const copy = { ...s, id: uid(), name: `${s.name} (copy)`, items: s.items.map((it) => ({ ...it, id: uid(), origId: '' })) }; const n = [...ss]; n.splice(i + 1, 0, copy); return n })}
                  onAdd={(kind) => setSection(s.id, { items: [...s.items, newItem(kind)] })}
                  onItem={(iid, patch) => setItem(s.id, iid, patch)}
                  onItemDelete={(iid) => setSection(s.id, { items: s.items.filter((it) => it.id !== iid) })}
                  onItemDup={(iid) => { const it = s.items.find((x) => x.id === iid); const i = s.items.findIndex((x) => x.id === iid); const copy = { ...it, id: uid(), origId: '' }; const n = [...s.items]; n.splice(i + 1, 0, copy); setSection(s.id, { items: n }) }}
                />
              ))}
            </SortableContext>
          </DndContext>
          <button onClick={() => setSections((ss) => [...ss, newSection()])} className="flex items-center gap-1.5 text-sm text-gold mt-2">
            <Plus className="w-4 h-4" /> Add section
          </button>
        </div>

        {showPreview && <Preview meta={meta} sections={sections} />}
      </div>
    </div>
  )
}

function SortableSection({ section, onName, onDelete, onDuplicate, onAdd, onItem, onItemDelete, onItemDup }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: section.id })
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.6 : 1 }
  return (
    <div ref={setNodeRef} style={style} className="border border-border rounded-xl bg-surface/40 p-3 mb-3">
      <div className="flex items-center gap-2 mb-2">
        <button {...attributes} {...listeners} className="cursor-grab text-text-faint hover:text-text touch-none"><GripVertical className="w-4 h-4" /></button>
        <input value={section.name} onChange={(e) => onName(e.target.value)}
          className="flex-1 bg-transparent text-sm font-medium text-text outline-none border-b border-transparent focus:border-gold/40 py-1" placeholder="Section name" />
        <button onClick={onDuplicate} className="text-text-faint hover:text-text" title="Duplicate section"><Copy className="w-4 h-4" /></button>
        <button onClick={onDelete} className="text-text-faint hover:text-red" title="Delete section"><Trash2 className="w-4 h-4" /></button>
      </div>

      <SortableContext items={section.items.map((it) => it.id)} strategy={verticalListSortingStrategy}>
        <div className="flex flex-col gap-2">
          {section.items.map((it) => (
            <SortableItem key={it.id} item={it} onChange={(patch) => onItem(it.id, patch)}
              onDelete={() => onItemDelete(it.id)} onDup={() => onItemDup(it.id)} />
          ))}
        </div>
      </SortableContext>

      <div className="flex flex-wrap gap-1.5 mt-2 pl-6">
        {TYPES.map((t) => {
          const Icon = t.icon
          return (
            <button key={t.k} onClick={() => onAdd(t.k)} title={t.hint}
              className="flex items-center gap-1 text-xs border border-border rounded-lg px-2 py-1 text-text-dim hover:border-gold/40">
              <Icon className="w-3 h-3" /> {t.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function SortableItem({ item, onChange, onDelete, onDup }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: item.id })
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.6 : 1 }
  const T = TYPES.find((t) => t.k === item.kind) || TYPES[0]
  const Icon = T.icon
  return (
    <div ref={setNodeRef} style={style} className="border border-border-soft rounded-lg bg-bg p-2">
      <div className="flex items-center gap-2">
        <button {...attributes} {...listeners} className="cursor-grab text-text-faint hover:text-text touch-none"><GripVertical className="w-4 h-4" /></button>
        <Icon className="w-4 h-4 text-gold-soft shrink-0" />
        <input value={item.label} onChange={(e) => onChange({ label: e.target.value })}
          className="flex-1 bg-transparent text-sm text-text outline-none border-b border-transparent focus:border-gold/40 py-1" placeholder="Check label" />
        <select value={item.kind} onChange={(e) => onChange({ kind: e.target.value })}
          className="bg-surface border border-border rounded px-2 py-1 text-xs text-text-dim outline-none">
          {TYPES.map((t) => <option key={t.k} value={t.k}>{t.label}</option>)}
        </select>
        <button onClick={onDup} className="text-text-faint hover:text-text" title="Duplicate"><Copy className="w-3.5 h-3.5" /></button>
        <button onClick={onDelete} className="text-text-faint hover:text-red" title="Delete"><X className="w-4 h-4" /></button>
      </div>
      {(item.kind === 'reading' || item.kind === 'state' || true) && (
        <div className="flex flex-wrap gap-2 mt-2 pl-12">
          {item.kind === 'reading' && <MiniInput label="Unit" value={item.unit} onChange={(v) => onChange({ unit: v })} w="w-24" />}
          {item.kind === 'state' && <MiniInput label="Options (comma)" value={item.options} onChange={(v) => onChange({ options: v })} w="w-56" />}
          {item.kind === 'state' && <MiniInput label="Issue options (comma)" value={item.alert} onChange={(v) => onChange({ alert: v })} w="w-44" />}
          <MiniInput label="Asset (optional)" value={item.asset} onChange={(v) => onChange({ asset: v })} w="w-40" />
        </div>
      )}
    </div>
  )
}

function MiniInput({ label, value, onChange, w }) {
  return (
    <label className="flex flex-col gap-0.5 text-[11px] text-text-faint">
      {label}
      <input value={value} onChange={(e) => onChange(e.target.value)}
        className={`${w} bg-surface border border-border rounded px-2 py-1 text-xs text-text outline-none focus:border-gold/40`} />
    </label>
  )
}

function Field({ label, children }) {
  return <label className="flex flex-col gap-1 text-xs text-text-faint">{label}{children}</label>
}

// Live technician-view preview
function Preview({ meta, sections }) {
  const total = sections.reduce((n, s) => n + s.items.filter((it) => it.label.trim()).length, 0)
  return (
    <div className="border border-border rounded-2xl bg-bg sticky top-4 overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <div className="text-sm font-medium text-text">{meta.name || 'Untitled checklist'}</div>
        <div className="text-xs text-text-faint">{total} checks{meta.timing ? ` · ${meta.timing}` : ''} · how the technician sees it</div>
      </div>
      <div className="max-h-[60vh] overflow-y-auto p-4 flex flex-col gap-4">
        {sections.map((s) => (
          <div key={s.id}>
            <div className="text-xs uppercase tracking-wide text-text-faint mb-2">{s.name || 'Section'}</div>
            <div className="flex flex-col gap-2">
              {s.items.filter((it) => it.label.trim()).map((it) => <PreviewItem key={it.id} item={it} />)}
            </div>
          </div>
        ))}
        {total === 0 && <div className="text-sm text-text-faint">Add checks to see the preview.</div>}
      </div>
    </div>
  )
}

function PreviewItem({ item }) {
  return (
    <div className="border border-border-soft rounded-xl p-3">
      <div className="text-sm text-text mb-2">{item.label}</div>
      {item.kind === 'tick' && (
        <div className="grid grid-cols-2 gap-2">
          <div className="py-2 rounded-lg border border-border text-center text-xs text-green flex items-center justify-center gap-1"><Check className="w-3 h-3" /> OK</div>
          <div className="py-2 rounded-lg border border-border text-center text-xs text-red flex items-center justify-center gap-1"><TriangleAlert className="w-3 h-3" /> Issue</div>
        </div>
      )}
      {item.kind === 'reading' && (
        <div className="flex items-center gap-2"><div className="flex-1 border border-border rounded-lg py-2 px-3 text-2xl font-serif text-text-faint">0</div><div className="text-sm text-text-faint">{item.unit || 'unit'}</div></div>
      )}
      {item.kind === 'state' && (
        <div className="flex flex-col gap-1.5">
          {(item.options.split(',').map((x) => x.trim()).filter(Boolean).length ? item.options.split(',').map((x) => x.trim()).filter(Boolean) : ['OK', 'ISSUE']).map((o) => {
            const isIssue = item.alert.split(',').map((x) => x.trim()).includes(o)
            return <div key={o} className={`py-2 rounded-lg border text-center text-sm ${isIssue ? 'border-red/40 text-red' : 'border-border text-text'}`}>{o}</div>
          })}
        </div>
      )}
      {item.kind === 'note' && <div className="border border-border rounded-lg p-2 text-xs text-text-faint">Type a note…</div>}
      <div className="mt-2 flex items-center gap-1 text-xs text-text-faint"><Camera className="w-3 h-3" /> add photo</div>
    </div>
  )
}
