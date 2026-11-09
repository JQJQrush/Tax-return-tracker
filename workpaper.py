"""Portable, printable human-entry workpaper. Not a ProSeries import format."""
from html import escape
from core import FIELDS


def render_workpaper(data,scope='reviewed'):
    if scope not in ['reviewed','draft']:raise ValueError('底稿范围无效')
    if scope=='reviewed' and any(i['severity']=='error' for i in data['review_checks']['issues']):raise ValueError('存在算式冲突或重复层级，请先处理；可导出含待核对的草稿底稿')
    def e(value):return escape(str(value if value is not None else '未填写'),quote=True)
    source=data['records'];refs=data['reference_records']
    if scope=='reviewed':
        source=[r for r in source if r['status']=='reviewed' and r.get('disposition')=='included']
        refs=[r for r in refs if r['status']=='reviewed' and r.get('disposition')=='included']
    owners={'taxpayer':'本人','spouse':'配偶','joint':'共同','return':'整份申报','unknown':'待确认'}
    status={'pending':'待核对','reviewed':'已核对','excluded':'已排除'}
    dispositions={'pending':'用途待确认','included':'用途已确认','excluded':'整页已排除'}
    def section(records):
        blocks=[]
        for r in records:
            fields=''.join(f'<tr><td>{e(label)}</td><td class="amount">{e(r["values"].get(key))}</td></tr>' for key,label in FIELDS[r['form_type']])
            brokerage=f"<p>证券分类：{e(r.get('category','unknown'))}；录入层级：{e({'summary':'分类汇总','detail':'单笔明细','unknown':'待确认'}.get(r.get('entry_level','unknown'),'待确认'))}</p>" if r['form_type']=='1099-B' else ''
            blocks.append(f'''<article><h3>#{r['id']} · {e(r['form_type'])} · {e(owners.get(r['owner'],'待确认'))}</h3>
<p>状态：{e(status.get(r['status'],r['status']))}；页面用途：{e(dispositions.get(r.get('disposition'),'用途待确认'))}；审核人：{e(r.get('reviewer') or '未填写')}</p>
<p>来源：{e(r['filename'])}，第 {r['page_number']} 页；付款方：{e(r.get('payer') or '未填写')}；账户代号：{e(r.get('account_alias') or '未填写')}</p>
{brokerage}
<table><thead><tr><th>原表字段</th><th>原始金额（保留分位）</th></tr></thead><tbody>{fields}</tbody></table>
<p class="notes">备注：{e(r.get('notes') or '无')}</p></article>''')
        return ''.join(blocks) or '<p>此范围没有记录。</p>'
    title='已核对录入底稿（数据子集）' if scope=='reviewed' else '草稿录入底稿（含待核对）'
    warnings=''.join(f'<li>{e(w)}</li>' for w in data['warnings'])
    issues=''.join(f'<li>{e(i["message"])}</li>' for i in data['review_checks']['issues'])
    unsupported='<p class="notice">当前税务年度未完成适配验证。</p>' if data['client']['tax_year']!=2025 else ''
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<style>body{{font:14px/1.6 "Microsoft YaHei",sans-serif;color:#173c36;max-width:950px;overflow-wrap:anywhere;margin:30px auto;padding:0 20px}}h1{{font-size:25px}}h2{{border-bottom:2px solid #167567;padding-bottom:7px}}article{{border:1px solid #d6e4dc;border-radius:8px;padding:16px;margin:16px 0;break-inside:avoid}}h3,p{{margin:5px 0}}table{{border-collapse:collapse;width:100%;margin:12px 0}}th,td{{border-bottom:1px solid #e0e8e1;text-align:left;padding:7px}}.amount{{font-variant-numeric:tabular-nums}}.notice{{padding:12px;background:#fff5dc;border-left:4px solid #bd8729}}.notes{{white-space:pre-wrap}}button{{font:inherit;padding:9px 16px;background:#176b59;color:white;border:0;border-radius:6px}}@media print{{button{{display:none}}body{{margin:0;padding:0;font-size:11px}}article{{border-radius:0}}}}</style></head><body>
<button onclick="window.print()">打印 / 另存 PDF</button><h1>{e(title)}</h1><p>客户代号：{e(data['client']['alias'])}；年度：{data['client']['tax_year']}；生成时间（UTC）：{e(data['generated_at'])}</p>
<p class="notice">供员工按原表字段人工录入和复核，不是 ProSeries 导入文件，不计算税额、不提交申报。金额保持原始分位，空白不等于零。范围匹配不代表客户资料完整。此文件包含客户财务资料，请妥善保存。</p>{unsupported}
<h2>使用范围及未完成事项</h2><ul>{warnings}{issues}</ul><p>{e(data['review_checks']['notice'])}</p>
<h2>原始收入资料 · {len(source)} 条</h2>{section(source)}<h2>完成税表对照 · {len(refs)} 条（不计入收入）</h2>{section(refs)}
<p>仅包含当前软件支持的字段。正式录入前核对未覆盖项目、税务年度、收入归属、证券汇总与明细范围及软件要求。</p></body></html>'''
