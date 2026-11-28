import { ArrowUp, BookOpen, CircleStop, FileText, Quote } from 'lucide-react'
import RetrievalFilters from '../../components/RetrievalFilters'
import { t } from '../../i18n'

export default function ChatComposer({
  draft,
  onDraftChange,
  onSend,
  switching,
  canSend,
  streaming,
  stopBusy,
  onStop,
  knowledgeBasesUnavailable,
  selectedKbIds,
  retrievalFilters,
  onRetrievalFiltersChange,
  selectedLabel,
  sourceCount,
  onOpenKnowledge,
  onToggleKnowledgeMenu,
  onOpenSources,
}) {
  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
      event.preventDefault()
      onSend()
    }
  }

  return (
    <form className="composer" onSubmit={onSend} aria-busy={switching}>
      <div className="composer-tools">
        <RetrievalFilters
          disabled={knowledgeBasesUnavailable || streaming}
          kbIds={selectedKbIds}
          value={retrievalFilters}
          onChange={onRetrievalFiltersChange}
        />
        <button type="button" onClick={onOpenKnowledge}><FileText size={14} />{t('导入资料')}</button>
        <button type="button" onClick={onToggleKnowledgeMenu}><Quote size={14} />{t('引用检索')}</button>
        <button type="button" onClick={onOpenSources}><BookOpen size={14} />{t('引用与原文')}{sourceCount ? ` · ${sourceCount}` : ''}</button>
      </div>
      <textarea
        aria-label={t('向忆知提问...')}
        value={draft}
        onChange={event => onDraftChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={t('向忆知提问...')}
        rows={1}
      />
      <span className="composer-context"><FileText size={14} />{selectedLabel}</span>
      {streaming
        ? <button type="button" className="stop-send" disabled={stopBusy} onClick={onStop} title={t('停止生成')} aria-label={t('停止生成')}><CircleStop size={19} /></button>
        : <button className="send-message" disabled={!canSend} title={t('发送')} aria-label={t('发送')}><ArrowUp size={20} /></button>}
    </form>
  )
}
