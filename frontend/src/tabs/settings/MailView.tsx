import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import { Button } from '../../ui/Button'
import { notify } from '../../ui/Toast'
import { Row, SubPage, TextInput } from './SubPage'

export function MailView({ onBack }: { onBack: () => void }) {
  const [server, setServer] = useState('smtp.gmail.com')
  const [port, setPort] = useState('465')
  const [sender, setSender] = useState('')
  const [password, setPassword] = useState('')
  const [goodnotes, setGoodnotes] = useState('')

  useEffect(() => {
    api()
      .then((a) => a.mail_settings())
      .then((s) => {
        if (!s.configured) return
        setServer(s.smtp_server ?? '')
        setPort(String(s.smtp_port ?? 465))
        setSender(s.sender_email ?? '')
        setGoodnotes(s.goodnotes_email ?? '')
      })
      .catch(() => undefined)
  }, [])

  const save = async () => {
    const r = await (await api()).save_mail_settings(
      server, Number(port), sender, password, goodnotes,
    )
    notify(r.success ? 'ok' : 'bad', r.success ? '已保存' : (r.error ?? '保存失败'))
  }

  const complete = server && port && sender && password && goodnotes

  return (
    <SubPage title="SMTP / GoodNotes" onBack={onBack}>
      <div className="rounded-ui border border-hairline bg-panel">
        <Row label="SMTP Server"><TextInput value={server} onChange={setServer} /></Row>
        <Row label="SMTP Port"><TextInput value={port} onChange={setPort} width="w-24" /></Row>
        <Row label="Sender Email"><TextInput value={sender} onChange={setSender} /></Row>
        <Row
          label="App Password"
          hint="不会回读 —— 存进 .env 之后这里始终是空的，重填即覆盖"
        >
          <TextInput type="password" value={password} onChange={setPassword} />
        </Row>
        <Row label="GoodNotes Email" hint="GoodNotes 的导入邮箱">
          <TextInput value={goodnotes} onChange={setGoodnotes} />
        </Row>
      </div>
      <Button tone="accent" onClick={save} disabled={!complete}>保存</Button>
    </SubPage>
  )
}
