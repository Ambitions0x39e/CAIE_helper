import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import { Banner } from '../../ui/Banner'
import { Button } from '../../ui/Button'
import { Row, SubPage, TextInput } from './SubPage'

export function GraderView({ onBack }: { onBack: () => void }) {
  const [key, setKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('qwen3.6-flash')
  const [configured, setConfigured] = useState(false)
  const [note, setNote] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)

  useEffect(() => {
    api()
      .then((a) => a.grader_settings())
      .then((s) => {
        setConfigured(Boolean(s.configured))
        setBaseUrl(s.base_url ?? '')
        if (s.model) setModel(s.model)
      })
      .catch(() => undefined)
  }, [])

  const save = async () => {
    const r = await (await api()).save_grader_settings(key, baseUrl, model)
    setNote(
      r.success
        ? { tone: 'ok', text: '已保存' }
        : { tone: 'bad', text: r.error ?? '保存失败' },
    )
    if (r.success) setConfigured(true)
  }

  return (
    <SubPage title="Grader API" onBack={onBack}>
      <div className="rounded-ui border border-hairline bg-panel">
        <Row
          label="API Key"
          hint={configured ? '已配置 —— 留空则不改动' : '还没配置，批改会用不了'}
        >
          <TextInput type="password" value={key} onChange={setKey} />
        </Row>
        <Row label="Base URL"><TextInput value={baseUrl} onChange={setBaseUrl} /></Row>
        <Row label="Model" hint="需支持图片输入的视觉/多模态模型">
          <TextInput value={model} onChange={setModel} />
        </Row>
      </div>
      {note && <Banner tone={note.tone} title={note.text} />}
      <Button tone="accent" onClick={save} disabled={!key}>保存</Button>
    </SubPage>
  )
}
