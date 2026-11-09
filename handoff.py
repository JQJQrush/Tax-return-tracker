"""Actionable review handoff for uploaded material; never filing readiness."""
from collections import Counter

NOTICE = '仅反映已上传资料及员工登记的应交项目；不判断客户是否交齐所有资料、税额是否正确，也不代表可申报。'


def build_handoff(records, pages, documents, report, intake=None):
    tasks = []
    def add(kind, message, page_id=None, record_id=None, severity='todo'):
        tasks.append(dict(kind=kind, message=message, page_id=page_id,
                          record_id=record_id, severity=severity))
    if not documents:
        add('upload', '尚未上传资料，请先上传客户原始资料。')
    for d in documents:
        if d['status'] != 'done':
            add('document', f"文件 #{d['id']}：{d.get('filename','')} 尚未完成识别，请检查或继续识别。",
                next((p['id'] for p in pages if p['document_id'] == d['id']), None))
        expected = d.get('page_count', 0)
        actual = sum(p['document_id'] == d['id'] for p in pages)
        if d['status'] == 'done' and (not actual or actual < expected):
            add('missing_pages', f"文件 #{d['id']} 页面不齐：预期 {expected} 页，当前 {actual} 页。", severity='error')
    for p in pages:
        if p['disposition'] == 'excluded':
            continue
        if p.get('error'):
            add('page_error', f"第 {p['page_number']} 页识别异常：{p['error']}", p['id'])
        if p['disposition'] == 'pending':
            add('page', f"{p.get('filename','')} 第 {p['page_number']} 页用途待确认。", p['id'])
        active = [r for r in records if r['page_id'] == p['id'] and r['status'] != 'excluded']
        if p['disposition'] == 'included' and not active:
            add('empty_page', f"第 {p['page_number']} 页已确认用途，但没有有效记录；请补录，或确认是否应排除此页。", p['id'])
        for r in active:
            if r['status'] != 'reviewed':
                add('record', f"记录 #{r['id']}（{r['form_type']}）尚未审核。", p['id'], r['id'])
    for issue in report['issues']:
        if issue['severity'] in ('warning', 'error') and not issue['message'].startswith('文件 #'):
            add('check', issue['message'], issue.get('page_id'), issue.get('record_id'), issue['severity'])
    for item in report['comparisons']:
        if item['status'] in ('difference', 'reference_conflict'):
            add('comparison', f"{item['label']}：原始金额 {item['source_total']}，对照 {item.get('reference') or '多值冲突'}，需要复查。", severity='warning')
    for item in intake or []:
        if item['state']=='missing':
            add('missing_document', f"待收资料：{item['label']}（员工登记）")
    completed = sum(p['disposition'] in ('included', 'excluded') for p in pages)
    return dict(filing_ready=False, tax_software_import_supported=False, notice=NOTICE,
                scope='uploaded_material_and_staff_expectations', page_total=len(pages), page_confirmed=completed,
                page_progress_percent=round(completed * 100 / len(pages)) if pages else 0,
                task_count=len(tasks), task_counts=dict(Counter(t['kind'] for t in tasks)),
                status='needs_review' if tasks else 'uploaded_review_complete', tasks=tasks)
