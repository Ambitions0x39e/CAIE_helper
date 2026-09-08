/** Run with `npm test` (node --test, no framework dependency).
 *
 * These pin what the command palette matches. The registry is data, so the
 * interesting part is all here: which words reach which destination.
 */
import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { COMMANDS, matchCommands, matchPapers, parseQuery, setTheme, theme, topicCommands } from './commands.ts'
import type { PaperRecord } from './types.ts'

const find = (q: string) => matchCommands(parseQuery(q))
const labels = (q: string) => find(q).map((c) => c.label)

const paper = (paper_id: string, qp_path: string): PaperRecord => ({
  paper_id,
  status: 'Pending',
  qp_path,
  ms_path: '',
  score_raw: null,
  score_total: null,
  sent_to_gn: false,
  timestamp: null,
  percentage: null,
})

describe('parseQuery — file 前缀切模式', () => {
  test('前缀带冒号、空格或什么都不带，都进 file 模式', () => {
    assert.equal(parseQuery('file:9709').mode, 'file')
    assert.equal(parseQuery('file 9709').mode, 'file')
    assert.equal(parseQuery('file').mode, 'file')
    assert.equal(parseQuery('FILE: 9709').mode, 'file')
  })

  test('前缀被剥掉，只留搜索内容', () => {
    assert.deepEqual(parseQuery('file: 9709 s25').tokens, ['9709 s25'])
    assert.deepEqual(parseQuery('file').tokens, [''])
  })

  test('没有分隔符就不是前缀', () => {
    assert.equal(parseQuery('filename').mode, 'default')
  })

  test('带数字的词是参数，不是过滤词', () => {
    const q = parseQuery('下载 9709')
    assert.deepEqual(q.tokens, ['下载'])
    assert.equal(q.param, '9709')
  })
})

describe('matchCommands', () => {
  test('助记串只中它自己那条 —— zl 是总览，不是整理', () => {
    assert.deepEqual(labels('zl'), ['总览'])
  })

  test('中文标签直接搜得到', () => {
    assert.ok(labels('分数线').includes('分数线'))
  })

  test('英文别名和标签等价', () => {
    assert.deepEqual(labels('gn'), ['SMTP / GoodNotes'])
  })

  test('大小写不敏感', () => {
    assert.deepEqual(labels('GN'), labels('gn'))
  })

  test('每个词都要中 —— 设置 API 落到 Grader API 那一页', () => {
    const hits = find('设置 API')
    assert.deepEqual(
      hits.map((c) => c.intent.view),
      ['grader'],
    )
  })

  test('分组名也参与匹配，这是「设置 API」能成立的原因', () => {
    assert.ok(labels('设置').includes('Grader API'))
  })

  test('无匹配返回空，不抛', () => {
    assert.deepEqual(find('zzzzz'), [])
  })

  test('空查询列出全部', () => {
    assert.equal(find('').length, COMMANDS.length)
  })

  test('参数挂到命中的 intent 上，registry 本身不变', () => {
    const hit = find('下载 9709').find((c) => c.id === 'dl.byid')
    assert.equal(hit?.intent.param, '9709')
    assert.equal(COMMANDS.find((c) => c.id === 'dl.byid')?.intent.param, undefined)
  })

  test('默认模式一条卷子也不出', () => {
    assert.deepEqual(find('9709'), [])
  })
})

describe('matchPapers — 只在 file 模式里', () => {
  const papers = [paper('9709_s25_12', '/pdf/a.pdf'), paper('9702_w24_11', '/pdf/b.pdf')]

  test('分隔符无所谓：空格、下划线、连写都找得到同一份', () => {
    for (const q of ['file 9709 s25 12', 'file:9709_s25_12', 'file 9709s25']) {
      assert.deepEqual(
        matchPapers(parseQuery(q), papers).map((c) => c.label),
        ['9709_s25_12'],
      )
    }
  })

  test('落点是那份卷子的 PDF 路径', () => {
    const [hit] = matchPapers(parseQuery('file 9709'), papers)
    assert.equal(hit.intent.open, '/pdf/a.pdf')
    assert.equal(hit.intent.tab, undefined)
  })

  test('光一个 file 列出全部', () => {
    assert.equal(matchPapers(parseQuery('file'), papers).length, 2)
  })
})

describe('topicCommands', () => {
  const topics = topicCommands(['9701 · Equilibria', '9701 · 未分类'])

  test('错题 Equilibria 落到该 topic 的筛选上', () => {
    const hits = matchCommands(parseQuery('错题 Equilibria'), topics)
    assert.equal(hits.length, 1)
    assert.deepEqual(hits[0].intent, {
      tab: 'manage',
      view: 'mistakes',
      sub: 'topic',
      param: '9701 · Equilibria',
    })
  })

  test('光输 错题 列出全部 topic', () => {
    assert.equal(matchCommands(parseQuery('错题'), topics).length, 2)
  })
})

describe('F1.4 —— 面板只能导航', () => {
  test('注册表里没有一条命令带得动函数', () => {
    for (const c of COMMANDS) {
      for (const v of Object.values(c.intent)) {
        assert.notEqual(typeof v, 'function', `${c.id} 的 intent 里有可执行的东西`)
      }
    }
  })
})

describe('主题', () => {
  const store = new Map<string, string>()
  globalThis.localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
  } as unknown as Storage
  const dataset: { theme?: string } = {}
  globalThis.document = { documentElement: { dataset } } as unknown as Document

  test('浅色深色落到 <html> 上，重开还记得', () => {
    setTheme('dark')
    assert.equal(dataset.theme, 'dark')
    assert.equal(theme(), 'dark')
  })

  test('跟随系统不留属性 —— 留了 prefers-color-scheme 就没得选了', () => {
    setTheme('dark')
    setTheme('system')
    assert.equal(dataset.theme, undefined)
    assert.equal(theme(), 'system')
  })

  test('存的是别的值也算跟随系统', () => {
    store.set('cie.theme', '"neon"')
    assert.equal(theme(), 'system')
  })
})
