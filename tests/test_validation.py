import json, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class RepositoryContractTests(unittest.TestCase):
    def test_negative_control_is_no_material(self):
        data=json.loads((ROOT/'data/reviewed/current_events.json').read_text())
        event=data['events'][0]
        self.assertTrue(event['negative_operational_evidence'])
        self.assertEqual(event['publication_status'],'No material impact detected')
        self.assertEqual(len(event['impact_assessments']),9)
        self.assertTrue(all(x['severity']=='none' for x in event['impact_assessments']))
    def test_no_missing_as_zero(self):
        text=(ROOT/'data/reviewed/current_events.json').read_text()
        self.assertNotIn('"unknown_value": 0',text)
    def test_dashboard_entry_exists(self):
        self.assertTrue((ROOT/'dashboard/public/index.html').exists())

if __name__=='__main__': unittest.main()
