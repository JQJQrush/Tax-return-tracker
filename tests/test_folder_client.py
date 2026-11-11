import sys,tempfile,unittest
from pathlib import Path
import pymupdf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from folder_client import names_from_text,folder_info

class FolderClientTests(unittest.TestCase):
    def pdf(self,folder,name,person):
        doc=pymupdf.open();page=doc.new_page();page.insert_text((50,50),"Taxpayer's name                 Social security number\n"+person+"                 000-00-0000")
        doc.save(Path(folder)/name);doc.close()
    def test_person_labels_and_multiple_copies(self):
        self.assertEqual(names_from_text("Taxpayer's name       Social security number\nELI CHEN        000-00-0000"),['ELI CHEN'])
        self.assertEqual(names_from_text("Employee's name and address\nELI CHEN ELI CHEN"),['ELI CHEN'])
        self.assertEqual(names_from_text("Employer's name\nACME COMPANY\nSpouse's name\nJANE DOE"),[])
        self.assertEqual(names_from_text('纳税人姓名：张三'),['张三'])
        self.assertEqual(names_from_text('Taxpayer name: Jane Doe'),['Jane Doe'])
    def test_content_name_not_folder_name(self):
        with tempfile.TemporaryDirectory(prefix='Misleading-Folder-') as folder:
            self.pdf(folder,'form.pdf','JANE DOE')
            info=folder_info(folder,read_name=True)
            self.assertEqual(info['name'],'JANE DOE')
            self.assertEqual(len(info['files']),1)
    def test_conflicting_names_and_no_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):folder_info(folder,read_name=True)
            self.pdf(folder,'a.pdf','JANE DOE');self.pdf(folder,'b.pdf','JOHN SMITH')
            with self.assertRaises(ValueError):folder_info(folder,read_name=True)
            self.assertIsNone(folder_info(folder,read_name=False)['name'])
    def test_relative_and_missing_path(self):
        for path in ['relative/path',r'Z:\definitely_missing_taxprep_qa']:
            with self.assertRaises(ValueError):folder_info(path)
