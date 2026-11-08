import json,tempfile,time,unittest
from pathlib import Path
try:
 from local_cv import DeckReferences
 from card_tracking import CardTracker,detect_quads,cv2,np
 from prepare_deck_references import seed
 from depth_filter import TableDepth
except ImportError:DeckReferences=None
ROOT=Path(__file__).parent/'validation/2026-11-08'
@unittest.skipIf(DeckReferences is None,'Requires blackjack CV runtime')
class LocalCVTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.bank=DeckReferences(Path(self.temp.name)/'deck.npz');seed(self.bank)
 def image(self,name):return cv2.cvtColor(cv2.imread(str(ROOT/name)),cv2.COLOR_BGR2RGB)
 def test_actual_repositioned_cards_read_without_a_model(self):
  tracker=CardTracker(self.bank);rgb=self.image('live-tracking/frame-180.jpg')
  for i in range(3):tracker.update(rgb,100+i/15,frame_id=i)
  cards=tracker.snapshot(100+2/15)['cards'];self.assertEqual({c['rank']+c['suit'] for c in cards if c['rank']},{'8♥','6♣'})
  self.assertTrue(all(c['identity_source']=='local_cv_reviewed_deck' for c in cards))
 def test_references_persist_and_report_only_actual_coverage(self):
  loaded=DeckReferences(self.bank.path);self.assertEqual(loaded.status()['learned_count'],7);self.assertEqual(loaded.status()['supported_faces'],52);self.assertTrue(loaded.status()['back_learned'])
 def test_blank_box_is_never_a_card(self):
  rgb=np.full((480,640,3),145,np.uint8);cv2.rectangle(rgb,(220,160),(275,240),(230,230,230),-1);cv2.putText(rgb,'BOX',(225,201),cv2.FONT_HERSHEY_SIMPLEX,.3,(70,70,70),1)
  tracker=CardTracker(self.bank)
  for i in range(3):tracker.update(rgb,100+i/15,frame_id=i)
  self.assertEqual(tracker.snapshot(100+2/15)['cards'],[])
 def test_back_reference_is_not_assigned_a_rank(self):
  back=next(e for e in self.bank.entries if e['rank']=='BACK');decision=self.bank.match([{'id':'back','patch':back['patch'],'colour':back['colour']}])['back']
  self.assertEqual(decision['face_state'],'down');self.assertIsNone(decision['rank'])
 def test_depth_rejects_box_and_accepts_table_plane(self):
  depth=np.full((480,640),1000,np.uint16);depth[160:240,220:275]=850
  frame={'camera_session_id':'test','reference_stream':'color','intrinsics':{'width':640,'height':480,'fx':600,'fy':600,'ppx':320,'ppy':240},'depth_z16':depth,'depth_scale_m':.001,'acquired_at_s':100,'depth_acquired_at_s':100}
  gate=TableDepth();gate.update(frame)
  self.assertEqual(gate.classify(frame,np.float32([[220,160],[275,160],[275,240],[220,240]]))['state'],'raised_or_nonplanar')
  self.assertEqual(gate.classify(frame,np.float32([[320,160],[370,160],[370,240],[320,240]]))['state'],'flat')
 def test_real_box_gripper_region_is_not_a_flat_table_card(self):
  with np.load(ROOT/'objects/current.npz') as z:
   frame=json.loads(z['metadata'].tobytes());frame['depth_z16']=z['depth'];frame['rgb']=z['rgb']
  gate=TableDepth();gate.update(frame);self.assertIsNone(gate.error)
  out=gate.classify(frame,np.float32([[190,165],[236,165],[236,215],[190,215]]));self.assertEqual(out['state'],'raised_or_nonplanar')
 def test_reference_requires_operator_confirmation(self):
  from camera_feed import Feed
  feed=Feed(None);feed.tracker=CardTracker(self.bank)
  with self.assertRaisesRegex(ValueError,'confirm'):feed.save_reference({'checked':False})
  with self.assertRaisesRegex(ValueError,'expired'):feed.save_reference({'checked':True,'capture_id':'unknown'})
if __name__=='__main__':unittest.main()
