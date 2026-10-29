import fs from 'node:fs'
import path from 'node:path'
import { parse } from '@babel/parser'
import traversePackage from '@babel/traverse'
const traverse = traversePackage.default
const messages = new Set()
const cjk = /[\u3400-\u9fff]/
for (const dir of ['pages', 'components']) {
  for (const file of fs.readdirSync(`src/${dir}`).filter(n => n.endsWith('.jsx') && !n.includes('.test.'))) {
    const ast = parse(fs.readFileSync(`src/${dir}/${file}`, 'utf8'), {sourceType:'module', plugins:['jsx']})
    traverse(ast, {
      StringLiteral(p) { if (cjk.test(p.node.value)) messages.add(p.node.value) },
      JSXText(p) { const text=p.node.value.replace(/\s+/g,' ').trim(); if(cjk.test(text)) messages.add(text) },
      TemplateLiteral(p) { const text=p.node.quasis.map((q,i)=>q.value.cooked+(i<p.node.expressions.length?`{${i}}`:'' )).join(''); if(cjk.test(text)) messages.add(text) },
    })
  }
}
fs.writeFileSync(path.resolve('../artifacts/translation-strings.json'), JSON.stringify([...messages], null, 2))
console.log(messages.size)
