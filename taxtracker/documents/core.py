"""Local tax document review primitives. No tax calculation or tax-software importer."""
import csv
import hashlib
import io
import json
import re
from decimal import Decimal, InvalidOperation

SCHEMA_VERSION = '0.7'
# Only an initial supported subset; blank is not zero.
FIELDS = {
    'W-2': [('wages', 'Box 1 工资'), ('federal_withheld', 'Box 2 联邦预扣'),
            ('ss_wages', 'Box 3 社安工资'), ('ss_withheld', 'Box 4 社安预扣'),
            ('medicare_wages', 'Box 5 Medicare 工资'), ('medicare_withheld', 'Box 6 Medicare 预扣'),
            ('state_wages', 'Box 16 州工资'), ('state_withheld', 'Box 17 州预扣')],
    'SSA-1099': [('benefits_paid', 'Box 3 已付福利'), ('benefits_repaid', 'Box 4 退还福利'),
                 ('net_benefits', 'Box 5 净福利'), ('federal_withheld', 'Box 6 联邦预扣')],
    '1099-INT': [('interest', 'Box 1 利息'), ('treasury_interest', 'Box 3 美国国债利息'),
                 ('federal_withheld', 'Box 4 联邦预扣'), ('foreign_tax', 'Box 6 外国税'),
                 ('tax_exempt_interest', 'Box 8 免税利息'), ('bond_premium', 'Box 11 债券溢价'),
                 ('treasury_bond_premium', 'Box 12 国债溢价'), ('exempt_bond_premium', 'Box 13 免税债券溢价')],
    '1099-DIV': [('ordinary_dividends', 'Box 1a 普通股息'), ('qualified_dividends', 'Box 1b 合格股息'),
                 ('capital_gain_distributions', 'Box 2a 资本利得分配'), ('nondividend_distributions', 'Box 3 非股息分配'),
                 ('federal_withheld', 'Box 4 联邦预扣'), ('section199a_dividends', 'Box 5 199A 股息'),
                 ('foreign_tax', 'Box 7 外国税'), ('exempt_interest_dividends', 'Box 12 免税股息')],
    '1099-B': [('proceeds', '卖出收入'), ('cost_basis', '成本'),
               ('wash_sale_disallowed', '不允许扣除的洗售亏损'), ('adjustment_amount', '其他调整（有符号；不含上项）'),
               ('reported_gain', '原资料列示收益 / 亏损（用于核对）')],
    '1040-reference': [('wages', '1040 1a 工资'), ('taxable_interest', '1040 2b 应税利息'),
                       ('qualified_dividends', '1040 3a 合格股息'), ('ordinary_dividends', '1040 3b 普通股息'),
                       ('social_security_total', '1040 6a 社安福利总额'), ('social_security_taxable', '1040 6b 应税社安福利'),
                       ('capital_gain', '1040 7a 资本收益'), ('agi', '1040 11a AGI'),
                       ('deductions', '1040 14 总扣除'), ('taxable_income', '1040 15 应税收入'),
                       ('total_tax', '1040 24 总税'), ('payments', '1040 33 总付款'),
                       ('amount_owed', '1040 37 应付金额'), ('estimated_penalty', '1040 38 预估税罚金')],
}
OWNERS = ['unknown', 'taxpayer', 'spouse', 'joint', 'return']
NUMERIC = re.compile(r'(?<![\w.-])\(?-?\$?\d[\d,]*\.\d{2}\)?(?!\d)')
OCR_SEPARATOR = '\n\n--- OCR block order / 文字区块顺序 ---\n'


def money(value):
    if value is None or str(value).strip() == '':
        return None
    raw = str(value).strip()
    if len(raw) > 40:
        raise ValueError('金额过长')
    if raw.startswith('(') and raw.endswith(')'):
        raw = '-' + raw[1:-1]
    raw = raw.replace('$', '').replace(',', '').strip()
    if not re.fullmatch(r'-?\d+(?:\.\d{1,2})?', raw):
        raise ValueError('金额只能使用数字、小数点或括号负数，最多两位小数')
    try:
        amount = Decimal(raw)
        if not amount.is_finite() or abs(amount) > Decimal('999999999999.99'):
            raise ValueError('金额超出范围')
        return format(amount.quantize(Decimal('.01')), 'f')
    except InvalidOperation as exc:
        raise ValueError('无效金额') from exc


def classify(text, role='source'):
    """Conservative page classification; metadata/instructions are never income."""
    t = ' '.join(text.upper().split())
    if role == 'reference':
        is_first = re.search(r'\b1040\b', t[:500]) and 'U.S. INDIVIDUAL INCOME TAX RETURN' in t[:500]
        is_second = re.match(r'FORM\s+1040\s+\(20\d\d\)', t)
        return ['1040-reference'] if is_first or is_second else []
    if any(x in t for x in ['INSTRUCTIONS FOR RECIPIENT', 'FACTS ABOUT YOUR']):
        # SSA-1099 pages contain a general-facts heading above the actual form.
        if 'SOCIAL SECURITY BENEFIT STATEMENT' not in t or 'BOX 5' not in t:
            return []
    if any(x in t for x in ['E-FILE SIGNATURE AUTHORIZATION', 'PAYMENT VOUCHER',
                             'ACKNOWLEDGEMENT AND GENERAL INFORMATION', 'INDIVIDUAL INCOME TAX RETURN']):
        return []
    if any(x in t for x in ['YEAR-END SUMMARY', 'SUPPLEMENTAL INFORMATION', 'SUMMARY OF 2025 PROCEEDS',
                            'TERMS AND CONDITIONS', 'DETAILS OF 1099-DIV']):
        return []
    found = []
    if re.search(r'SSA\s*[-—–]?\s*1099', t) and 'SOCIAL SECURITY BENEFIT' in t:
        return ['SSA-1099']
    if re.search(r'W\s*[-—–]?\s*2\b', t) and any(x in t for x in ['WAGE', 'EARNINGS']) and not re.search(r'(?:^|\n)\s*INSTRUCTIONS FOR EMPLOYEE\b', text, re.I):
        found.append('W-2')
    for form in ['INT', 'DIV', 'B']:
        if re.search(r'''1099[\s\-—–‘’'"]*''' + form + r'\b', t):
            if form=='INT' and 'INTEREST INCOME' not in t:
                continue
            if form=='DIV' and not any(x in t for x in ['ORDINARY DIVIDENDS', 'DIVIDENDS AND DISTRIBUTIONS']):
                continue
            if form=='B' and not re.search(r'PROCEEDS FROM BROKER|(?:SHORT|LONG).TERM TRANSACTIONS',t):
                continue
            found.append('1099-' + form)
    if ('1099-INT' not in found and 'FORM 1099 COMPOSITE' in t and 'INTEREST INCOME' in t
            and 'TREASURY OBLIGATIONS' in t):
        found.append('1099-INT')
    # A cover/contents/instructions page mentioning forms is not an input page.
    if ('TABLE OF CONTENTS' in t or 'ITEMS FOR ATTENTION' in t or 'INSTRUCTIONS FOR RECIPIENT' in t[:1000]
            or any(re.match(r'\s*NOTES FOR YOUR FORM', line, re.I) for line in text.splitlines()[:20])):
        return []
    return found


# Label + amount on the same OCR line only. Unclear column layouts stay blank.
LABELS = {
    '1099-DIV': {'ordinary_dividends': r'total ordinary dividends', 'qualified_dividends': r'^\s*(?:1b\s+)?qualified dividends',
                 'capital_gain_distributions': r'total capital gain distr', 'section199a_dividends': r'section 199a dividends',
                 'nondividend_distributions': r'non.?dividend distributions', 'foreign_tax': r'foreign tax paid',
                 'exempt_interest_dividends': r'exempt.interest dividends'},
    '1099-INT': {'interest': r'^\s*(?:[1+]\s+)?interest income', 'treasury_interest': r'interest on u\.?s\.? savings',
                 'tax_exempt_interest': r'^\s*(?:8\s+)?tax.exempt interest', 'foreign_tax': r'foreign tax paid'},
    'SSA-1099': {'net_benefits': r'box 5.*net benefits', 'benefits_paid': r'box 3.*benefits paid',
                 'benefits_repaid': r'box 4.*benefits repaid', 'federal_withheld': r'box 6.*voluntary federal'},
    'W-2': {'wages': r'^\s*1\s+wages,? tips', 'federal_withheld': r'^\s*2\s+federal income tax withheld'},
}


def suggestions(text, form):
    if OCR_SEPARATOR in text:
        parts=text.split(OCR_SEPARATOR)
        merged={}
        offset=0
        for part in parts:
            for key, candidate in suggestions(part,form).items():
                item={**candidate,'line':candidate['line']+offset}
                merged.setdefault(key,[]).append(item)
            offset+=len(part.splitlines())+3
        # Conflicting OCR views are deliberately left blank.
        return {key:items[0] for key,items in merged.items() if len({v['value'] for v in items})==1}
    result = {}
    for field, pattern in LABELS.get(form, {}).items():
        candidates = []
        for number, line in enumerate(text.splitlines(), 1):
            match = re.search(pattern, line, re.I)
            if match:
                values = NUMERIC.findall(line[match.end():])
                if len(values) == 1:
                    candidates.append((money(values[0]), number, line.strip()))
        # Multiple occurrences, even identical values, require human selection.
        if len(candidates) == 1:
            value, line, excerpt = candidates[0]
            result[field] = {'value': value, 'method': 'same_line_label', 'line': line,
                             'evidence': excerpt, 'review_status': 'pending'}
    return result


def validate_record(data):
    form = data.get('form_type')
    if form not in FIELDS:
        raise ValueError('暂不支持该表格')
    owner = data.get('owner', 'unknown')
    if owner not in OWNERS:
        raise ValueError('收入归属无效')
    allowed = {k for k, _ in FIELDS[form]}
    if set(data.get('values', {})) - allowed:
        raise ValueError('出现未知字段，请先使用对应表格')
    values = {k: money(data.get('values', {}).get(k)) for k in allowed}
    status = data.get('status', 'pending')
    if status not in ['pending', 'reviewed', 'excluded']:
        raise ValueError('审核状态无效')
    reviewer = str(data.get('reviewer', '')).strip()[:100]
    if status == 'reviewed':
        if not reviewer or owner == 'unknown' or not data.get('confirmed_blanks'):
            raise ValueError('核对通过前，请填写审核人、确认归属，并逐项确认空白字段')
        if not any(v is not None for v in values.values()):
            raise ValueError('至少填写一个已核对金额；无关表格请排除')
    if form == '1040-reference' and owner != 'return':
        raise ValueError('税表对照记录必须选择整份申报')
    if form != '1040-reference' and owner == 'return':
        raise ValueError('收入资料请选择本人、配偶或共同')
    if form in ['W-2','SSA-1099'] and owner == 'joint':
        raise ValueError('W-2 和 SSA-1099 请分别归属本人或配偶')
    category = str(data.get('category', 'unknown'))
    if category not in ['unknown', 'A', 'B', 'C', 'D', 'E', 'F']:
        raise ValueError('证券分类无效；本版仅支持非数字资产 A–F')
    if form == '1099-B' and status == 'reviewed' and category == 'unknown':
        raise ValueError('证券记录须核对 8949 的 A–F 分类')
    entry_level=data.get('entry_level','unknown')
    if entry_level not in ['unknown','summary','detail']:raise ValueError('证券录入层级无效')
    if form=='1099-B' and status=='reviewed' and entry_level=='unknown':
        raise ValueError('证券记录须确认是分组汇总还是交易明细')
    return {'form_type': form, 'owner': owner, 'values': values, 'status': status,
            'reviewer': reviewer, 'confirmed_blanks': bool(data.get('confirmed_blanks')),
            'payer': str(data.get('payer', '')).strip()[:200],
            'account_alias': str(data.get('account_alias', '')).strip()[:100],
            'category': category, 'entry_level':entry_level, 'notes': str(data.get('notes', ''))[:4000]}


def export_rows(records):
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(['tax_year', 'client_id', 'document', 'page', 'record_id', 'form_type',
                     'owner', 'payer', 'account_alias', 'category', 'field', 'value', 'reviewer','entry_level'])
    for rec in records:
        for field, value in rec['values'].items():
            if value is None:
                continue
            row = [rec['tax_year'], rec['client_id'], rec['filename'], rec['page_number'], rec['id'],
                   rec['form_type'], rec['owner'], rec.get('payer', ''), rec.get('account_alias', ''),
                   rec.get('category', ''), field, value, rec.get('reviewer', ''),rec.get('entry_level','unknown')]
            # Prevent spreadsheet formula evaluation in user-entered text cells.
            row = [('\'' + x if isinstance(x, str) and x[:1] in '=+@-' and i != 11 else x)
                   for i, x in enumerate(row)]
            writer.writerow(row)
    return out.getvalue()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def aligned_ocr_text(tsv):
    """Reassemble visual rows across OCR blocks (brokerage amount columns split blocks)."""
    rows = []
    for word in csv.DictReader(io.StringIO(tsv), delimiter='\t', quoting=csv.QUOTE_NONE):
        text = word.get('text', '').strip()
        if not text or word.get('level')!='5':
            continue
        try:
            top, height, left = int(word['top']), int(word['height']), int(word['left'])
        except (ValueError,KeyError):
            continue
        center = top + height/2
        match = next((r for r in reversed(rows[-20:]) if abs(r['center']-center) <= max(3,min(r['height'],height)*.42)),None)
        if match is None:
            rows.append({'center':center,'height':height,'words':[(left,text)]})
        else:
            match['words'].append((left,text))
    return '\n'.join(' '.join(text for left,text in sorted(row['words'])) for row in sorted(rows,key=lambda r:r['center']))


def block_ocr_text(tsv):
    rows={}
    for word in csv.DictReader(io.StringIO(tsv),delimiter='\t',quoting=csv.QUOTE_NONE):
        if word.get('level')!='5' or not word.get('text','').strip():
            continue
        key=tuple(word.get(k,'') for k in ['page_num','block_num','par_num','line_num'])
        rows.setdefault(key,[]).append(word['text'].strip())
    return '\n'.join(' '.join(words) for words in rows.values())
