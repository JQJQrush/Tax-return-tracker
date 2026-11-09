"""Review assistance and limited arithmetic comparisons, never a tax engine."""
from decimal import Decimal,ROUND_HALF_UP
import json


def checks(records,pages,documents):
    issues=[];metrics=[]
    for d in documents:
        if d['status']!='done':issues.append({'severity':'warning','message':f"文件 #{d['id']} 尚未完成识别"})
    for p in pages:
        if p.get('disposition')=='pending':issues.append({'severity':'todo','page_id':p['id'],'message':f"{p.get('filename') or ('文件 #'+str(p.get('document_id','?')))} 第 {p['page_number']} 页用途待确认"})
    active=[r for r in records if r.get('disposition')!='excluded' and r['status']!='excluded']
    for r in active:
        v=r['values'];rid=r['id']
        if r['status']!='reviewed':issues.append({'severity':'todo','record_id':rid,'page_id':r['page_id'],'message':f"记录 #{rid} 尚未审核"})
        if r['form_type']=='SSA-1099' and all(v.get(k) is not None for k in ['benefits_paid','benefits_repaid','net_benefits']):
            if Decimal(v['benefits_paid'])-Decimal(v['benefits_repaid'])!=Decimal(v['net_benefits']):
                issues.append({'severity':'error','record_id':rid,'page_id':r['page_id'],'message':'SSA-1099：已付福利 − 退还福利不等于净福利'})
        if r['form_type']=='1099-B':
            if r.get('entry_level','unknown')=='unknown':issues.append({'severity':'warning','record_id':rid,'page_id':r['page_id'],'message':'证券记录未确认汇总 / 明细层级'})
            if all(v.get(k) is not None for k in ['proceeds','cost_basis','wash_sale_disallowed','reported_gain']):
                computed=Decimal(v['proceeds'])-Decimal(v['cost_basis'])+Decimal(v['wash_sale_disallowed'])+Decimal(v.get('adjustment_amount') or '0')
                if abs(computed-Decimal(v['reported_gain']))>Decimal('.01'):
                    issues.append({'severity':'error','record_id':rid,'page_id':r['page_id'],'message':'证券收益与卖出收入 − 成本 + 洗售及其他调整不一致；其他调整空白仅在此算式中按 0 试算'})
    # Suggest duplicates only with matching identity context and values, never amount alone.
    signatures={}
    for r in active:
        if r['role']!='source' or not r.get('payer') or not r.get('account_alias') or r['owner']=='unknown':continue
        if not any(v is not None for v in r['values'].values()):continue
        key=(r['form_type'],r['owner'],r['payer'].casefold(),r['account_alias'].casefold(),json.dumps(r['values'],sort_keys=True))
        if key in signatures:issues.append({'severity':'warning','record_id':r['id'],'page_id':r['page_id'],'message':f"与记录 #{signatures[key]} 的付款方、账户、归属及金额相同，可能重复；请人工核对"})
        else:signatures[key]=r['id']
    brokerage={}
    for r in active:
        if r['role']=='source' and r['form_type']=='1099-B':
            identity=(r['payer'].casefold(),r['account_alias'].casefold(),r['owner']) if r.get('payer') and r.get('account_alias') and r['owner']!='unknown' else (r['document_id'],r.get('account_alias',''),r['owner'])
            brokerage.setdefault((identity,r.get('category','unknown')),set()).add(r.get('entry_level','unknown'))
    if any('summary' in levels and 'detail' in levels for levels in brokerage.values()):
        issues.append({'severity':'error','message':'同一文件/账户的同一证券分类同时保留汇总和交易明细，可能重复计入'})
    mapping=[('工资','wages',[('W-2','wages')]),('联邦预扣（仅 W-2，不含其他付款）','w2_withheld',[('W-2','federal_withheld')]),
             ('普通股息','ordinary_dividends',[('1099-DIV','ordinary_dividends')]),('合格股息','qualified_dividends',[('1099-DIV','qualified_dividends')]),
             ('社安福利总额','social_security_total',[('SSA-1099','net_benefits')])]
    # No interest/taxable-SSA/capital-gain comparison: those can require adjustments and tax rules.
    for label,refkey,sources in mapping:
        if refkey=='w2_withheld':continue  # 1040 total payments is not the same as W-2 withholding.
        rows=[r for r in active if r['role']=='source' and (r['form_type'],sources[0][1]) in sources]
        refs=[Decimal(r['values'][refkey]) for r in active if r['role']=='reference' and r['status']=='reviewed' and r.get('disposition')=='included' and r['values'].get(refkey) is not None]
        incomplete=not rows or any(r['status']!='reviewed' or r.get('disposition')!='included' or r['values'].get(sources[0][1]) is None for r in rows)
        incomplete=incomplete or any(d['role']=='source' and d['status']!='done' for d in documents)
        incomplete=incomplete or any(p.get('disposition')=='pending' for p in pages if p.get('role')=='source')
        total=sum((Decimal(r['values'][sources[0][1]]) for r in rows if r['values'].get(sources[0][1]) is not None),Decimal(0))
        distinct=set(refs)
        status='incomplete' if incomplete else 'missing_reference' if not refs else 'reference_conflict' if len(distinct)>1 else 'match' if total.quantize(Decimal('1'),rounding=ROUND_HALF_UP)==refs[0] else 'difference'
        metrics.append({'label':label,'source_total':format(total,'.2f'),'reference':str(refs[0]) if len(distinct)==1 else None,
                        'difference':str(total-refs[0]) if len(distinct)==1 else None,'status':status})
    return {'issues':issues,'comparisons':metrics,'notice':'仅比较当前支持字段的已录入数据；匹配不代表资料完整、税额正确或申报可提交。按合计金额四舍五入到整美元作提示，逐项舍入也可能产生差异。'}
