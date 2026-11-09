"""Staff-maintained expected documents, not a tax eligibility questionnaire."""
STATES = {'missing':'待收', 'received':'已收', 'not_applicable':'不适用'}
OWNERS = {'unknown':'待确认','taxpayer':'本人','spouse':'配偶','joint':'共同'}

def validate_item(data):
    result = {k:str(data.get(k,'')).strip() for k in ('label','owner','state','notes','reviewer')}
    if not result['label'] or len(result['label'])>200:raise ValueError('资料名称须为 1–200 字')
    if result['owner'] not in OWNERS or result['state'] not in STATES:raise ValueError('资料归属或状态无效')
    if len(result['notes'])>2000 or len(result['reviewer'])>100:raise ValueError('备注或经办人过长')
    if not result['reviewer']:raise ValueError('请填写经办人')
    if result['state']=='not_applicable' and not result['notes']:raise ValueError('不适用项目须填写原因')
    doc=data.get('document_id')
    result['document_id']=int(doc) if doc not in (None,'') else None
    if result['state']!='received' and result['document_id'] is not None:raise ValueError('只有已收项目可以关联文件')
    return result

def reminder(client,items):
    pending=[i for i in items if i['state']=='missing']
    lines=[f"客户代号：{client['alias']} / 税务年度：{client['tax_year']}", '待补资料清单（员工审核后自行发送）', '']
    lines += [f"{n}. {i['label']}（{OWNERS[i['owner']]}）" for n,i in enumerate(pending,1)]
    if not pending:lines+=['当前人工维护清单没有待收项目；不表示所有报税资料已齐全。']
    lines += ['', '以上只根据员工登记的项目生成；请确认实际适用情况。', '请通过双方约定的安全渠道提供资料，请勿直接回复完整身份号码、银行账号或密码。']
    return '\n'.join(lines)+'\n'
