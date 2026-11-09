"""Conservative geometry-based candidates. Every result still requires review."""
import csv
import io
import re
from core import money


def ocr_words(tsv, width, height):
    result=[]
    for w in csv.DictReader(io.StringIO(tsv),delimiter='\t',quoting=csv.QUOTE_NONE):
        if w.get('level')!='5' or not w.get('text','').strip():continue
        try:
            box=[int(w['left'])/width,int(w['top'])/height,int(w['width'])/width,int(w['height'])/height]
            result.append({'text':w['text'].strip(),'box':box,'confidence':float(w['conf'])})
        except (KeyError,ValueError):continue
    return result


def clean(text):return re.sub(r'[^a-z0-9-]','',text.lower())
def cy(w):return w['box'][1]+w['box'][3]/2


def phrases(words, tokens):
    hits=[]
    for anchor in words:
        if clean(anchor['text'])!=tokens[0]:continue
        row=sorted([w for w in words if abs(cy(w)-cy(anchor))<.009 and w['box'][0]>=anchor['box'][0]-.001
                    and amount_token(w) is None and clean(w['text'])],key=lambda w:w['box'][0])
        index=0;last=anchor['box'][0]
        for w in row:
            if index<len(tokens) and clean(w['text'])==tokens[index] and w['box'][0]-last<.13:
                last=w['box'][0];index+=1
        if index==len(tokens) and last-anchor['box'][0]<.35:hits.append(anchor)
    return sorted(hits,key=lambda w:(w['box'][1],w['box'][0]))


def amount_token(w, allow_none=False):
    raw=w['text'].strip().replace('§','$')
    if allow_none and raw.upper()=='NONE':return '0.00'
    if not re.fullmatch(r'\(?-?\$?\d[\d,]*\.\d{2}\)?',raw):return None
    try:return money(raw)
    except ValueError:return None


def evidence(w, method):
    return {'value':amount_token(w,True),'method':method,'line':None,'box':w['box'],
            'confidence':w.get('confidence'),'evidence':w['text'],'review_status':'pending'}


def cell(words, anchor, right, depth=.045, allow_none=False):
    x,y,width,height=anchor['box']
    candidates=[w for w in words if x-.008<=w['box'][0]<right and
                w['box'][0]+w['box'][2]<=right+.005 and cy(anchor)+.002<cy(w)<cy(anchor)+depth
                and amount_token(w,allow_none) is not None]
    candidates.sort(key=cy)
    if not candidates:return None
    first=candidates[0]
    near=[w for w in candidates if abs(cy(w)-cy(first))<.008]
    return first if len(near)==1 else None


def w2_candidates(words):
    labels={'wages':['wages','tips','other','comp'],
            'federal_withheld':['federal','income','tax','withheld'],
            'ss_wages':['social','security','wages'], 'ss_withheld':['social','security','tax','withheld'],
            'medicare_wages':['medicare','wages','and','tips'], 'medicare_withheld':['medicare','tax','withheld']}
    anchors={key:phrases(words,tokens) for key,tokens in labels.items()}
    # Select one uppermost W-2 copy, never merge multiple copies by their amounts.
    if not anchors['wages']:return {}
    wages=anchors['wages'][0]
    federal=next((w for w in anchors['federal_withheld'] if abs(cy(w)-cy(wages))<.025 and w['box'][0]>wages['box'][0]),None)
    if not federal:return {}
    left=wages['box'][0];middle=federal['box'][0]-.008
    right=middle+(middle-left)
    result={}
    for key in labels:
        left_column=key in ['wages','ss_wages','medicare_wages']
        eligible=[w for w in anchors[key] if cy(wages)-.025<=cy(w)<=cy(wages)+.09 and
                  (left-.015<=w['box'][0]<middle if left_column else middle<=w['box'][0]<right)]
        if not eligible:continue
        found=cell(words,eligible[0],middle if left_column else right,depth=.028)
        if found:result[key]=evidence(found,'w2_cell')
    return result


def ssa_candidates(words):
    anchors={n:phrases(words,['box',str(n)]) for n in [3,4,5,6]}
    triples=[]
    for a in anchors[3]:
        for b in anchors[4]:
            for c in anchors[5]:
                if a['box'][0]<b['box'][0]<c['box'][0] and max(cy(a),cy(b),cy(c))-min(cy(a),cy(b),cy(c))<.025:
                    triples.append((a,b,c))
    if len(triples)!=1:return {}
    a,b,c=triples[0];result={}
    for key,anchor,right in [('benefits_paid',a,b['box'][0]-.008),('benefits_repaid',b,c['box'][0]-.008),('net_benefits',c,1.)]:
        found=cell(words,anchor,right,depth=.065,allow_none=True)
        if found:result[key]=evidence(found,'ssa_box_cell')
    for anchor in anchors[6]:
        if cy(anchor)>cy(c):
            found=cell(words,anchor,1.,depth=.065,allow_none=True)
            if found:result['federal_withheld']=evidence(found,'ssa_box_cell');break
    return result


def broker_candidates(words):
    if not any(clean(w['text'])=='schwab' for w in words):return {}
    result={}
    for term in ['short-term','long-term']:
        for anchor in phrases(words,['total',term]):
            row=[w for w in words if abs(cy(w)-cy(anchor))<.013]
            line=' '.join(w['text'] for w in sorted(row,key=lambda w:w['box'][0])).lower()
            # Only category totals explicitly naming IRS basis status; never security subtotals.
            if 'cost' not in line or 'basis' not in line or 'reported' not in line:continue
            amounts=[w for w in words if w['box'][0]>.45 and cy(anchor)-.014<cy(w)<cy(anchor)+.032 and amount_token(w) is not None]
            amounts.sort(key=lambda w:w['box'][0])
            if not 3<=len(amounts)<=4:continue
            if not (.48<amounts[0]['box'][0]<.61 and .60<amounts[1]['box'][0]<.69 and .68<amounts[2]['box'][0]<.82):continue
            if len(amounts)==4 and amounts[3]['box'][0]<.82:continue
            if result:return {}  # More than one category on the page needs separate manual records.
            for key,w in zip(['proceeds','cost_basis','wash_sale_disallowed','reported_gain'],amounts):
                result[key]=evidence(w,'broker_category_total')
    return result


def layout_candidates(words,form):
    return {'W-2':w2_candidates,'SSA-1099':ssa_candidates,'1099-B':broker_candidates,
            '1040-reference':reference_candidates}.get(form,lambda _:{})(words)


def reference_candidates(words):
    codes={'1a':'wages','2b':'taxable_interest','3a':'qualified_dividends','3b':'ordinary_dividends',
           '6a':'social_security_total','6b':'social_security_taxable','7a':'capital_gain','11a':'agi','11b':'agi',
           '14':'deductions','15':'taxable_income','24':'total_tax','33':'payments','37':'amount_owed','38':'estimated_penalty'}
    collected={}
    for anchor in words:
        code=clean(anchor['text'])
        if code not in codes:continue
        if anchor['box'][0] < (.25 if code in ['3a','6a','38'] else .75):continue
        candidates=[]
        for w in words:
            if abs(cy(w)-cy(anchor))>.008 or not anchor['box'][0]+anchor['box'][2]<w['box'][0]<anchor['box'][0]+.32:continue
            raw=w['text'].strip()
            if re.fullmatch(r'-?\d[\d,]*\.',raw):value=money(raw[:-1])
            else:value=amount_token(w)
            if value is not None:candidates.append((w,value))
        if not candidates:continue
        w,value=min(candidates,key=lambda item:item[0]['box'][0])
        item=evidence(w,'1040_return_cell');item['value']=value
        collected.setdefault(codes[code],[]).append(item)
    return {key:items[0] for key,items in collected.items() if len({v['value'] for v in items})==1}


def combine_candidates(text_candidates,layout):
    result=dict(text_candidates)
    for key,item in layout.items():
        if key in result and result[key]['value']!=item['value']:
            result.pop(key)  # Conflict is left for manual entry.
        else:result[key]=item
    return result
