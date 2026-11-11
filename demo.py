"""Entirely synthetic documents for installation and tester onboarding."""
import pymupdf as fitz


def demo_documents():
    source=fitz.open()
    p=source.new_page();p.insert_text((40,55),'SYNTHETIC SAMPLE - W-2',fontsize=18)
    p.insert_text((40,85),'W-2 Wage and Tax Statement 2025',fontsize=12)
    rows=[(150,'1 Wages, tips, other comp.','2 Federal income tax withheld','1000.50','100.00'),
          (180,'3 Social security wages','4 Social security tax withheld','1000.50','62.03'),
          (210,'5 Medicare wages and tips','6 Medicare tax withheld','1000.50','14.51')]
    for y,left,right,a,b in rows:
        p.insert_text((40,y),left,fontsize=10);p.insert_text((330,y),right,fontsize=10)
        p.insert_text((100,y+15),a,fontsize=11);p.insert_text((400,y+15),b,fontsize=11)
    p.insert_text((40,400),'NOT A REAL TAX DOCUMENT. No identifying information.',fontsize=10)
    p=source.new_page();p.insert_text((40,55),'FORM SSA-1099',fontsize=18)
    p.insert_text((40,85),'SOCIAL SECURITY BENEFIT STATEMENT - SYNTHETIC',fontsize=11)
    for x,t in [(40,'Box 3. Benefits Paid'),(220,'Box 4. Benefits Repaid'),(410,'Box 5. Net Benefits')]:p.insert_text((x,300),t,fontsize=10)
    for x,t in [(90,'$200.50'),(275,'NONE'),(470,'$200.50')]:p.insert_text((x,325),t,fontsize=12)
    p.insert_text((220,450),'Box 6. Voluntary Federal Income Tax Withheld',fontsize=10)
    p.insert_text((280,475),'NONE',fontsize=12)
    p=source.new_page();p.insert_text((40,55),'Form 1099-DIV - SYNTHETIC',fontsize=17)
    p.insert_text((40,140),'1a Total Ordinary Dividends 300.50\n1b Qualified Dividends 20.50',fontsize=12)
    p.insert_text((40,400),'NOT A REAL TAX DOCUMENT. No identifying information.',fontsize=10)
    reference=fitz.open();p=reference.new_page()
    p.insert_text((40,55),'Form 1040 U.S. Individual Income Tax Return 2025',fontsize=13)
    p.insert_text((40,85),'SYNTHETIC REFERENCE ONLY - NOT A FILEABLE RETURN',fontsize=10)
    for x,y,t in [(500,150,'1a'),(550,150,'1001.'),(200,210,'3a'),(280,210,'21.'),
                  (500,210,'3b'),(550,210,'301.'),(200,270,'6a'),(280,270,'201.')]:p.insert_text((x,y),t,fontsize=12)
    result=(source.tobytes(),reference.tobytes());source.close();reference.close();return result
