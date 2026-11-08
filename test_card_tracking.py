"""Geometry/identity regressions using real saved overhead pixels; no devices."""
import json,time,unittest
from pathlib import Path
try:
    from card_tracking import CardTracker,detect_quads,cv2,np
except ImportError:
    CardTracker=None

ROOT=Path(__file__).parent/'validation'/'2026-11-08'

@unittest.skipIf(CardTracker is None,'Local tracking runtime requires OpenCV')
class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.rgb=cv2.cvtColor(cv2.imread(str(ROOT/'fresh-1.jpg')),cv2.COLOR_BGR2RGB)
        self.read=json.loads((ROOT/'fresh-1.json').read_text());self.read['captured_at']=100.2
        self.tracker=CardTracker()
        for i in range(3):self.tracker.update(self.rgb,100+i*.1,frame_id=i)
        self.tracker.apply_read(self.read)
    def visible(self,at=100.2):return [c for c in self.tracker.snapshot(at)['cards'] if c['visible']]
    def test_actual_three_cards_and_empty_table(self):
        self.assertEqual({c['rank']+c['suit'] for c in self.visible()},{'8♥','6♣','3♥'})
        empty=cv2.cvtColor(cv2.imread(str(ROOT/'empty-table-1.jpg')),cv2.COLOR_BGR2RGB)
        self.assertEqual(detect_quads(empty),[])
    def test_continuous_translation_and_rotation_keep_identity(self):
        initial={c['id']:np.array(c['corners'])*[640,480] for c in self.visible()}
        for i in range(1,11):
            m=cv2.getRotationMatrix2D((280,120),i*.6,1);m[:,2]+=[i*1.5,i*.7]
            rgb=cv2.warpAffine(self.rgb,m,(640,480),borderMode=cv2.BORDER_REFLECT)
            self.tracker.update(rgb,100.2+i*.1,frame_id=2+i)
        cards=self.visible(101.2)
        self.assertEqual({c['rank']+c['suit'] for c in cards},{'8♥','6♣','3♥'})
        for card in cards:
            expected=cv2.transform(initial[card['id']][None],m)[0]
            actual=np.array(card['corners'])*[640,480]
            self.assertLess(np.max(np.linalg.norm(actual-expected,axis=1)),2)
    def test_occlusion_removes_label_and_delayed_result_cannot_restore_it(self):
        hidden=self.rgb.copy();hidden[80:165,180:235]=[160,165,160]
        self.tracker.update(hidden,100.3,frame_id=3)
        self.tracker.apply_read(self.read)
        self.assertNotIn('8',[c['rank'] for c in self.visible(100.3)])
        self.tracker.update(self.rgb,100.4,frame_id=4)
        returned=[c for c in self.visible(100.4) if c['rank']=='8']
        self.assertEqual(len(returned),1)
        self.assertEqual(returned[0]['identity_source'],'local_verified_face_match')
    def test_real_repositioned_cards_reidentified_without_model(self):
        moved=cv2.cvtColor(cv2.imread(str(ROOT/'live-tracking'/'frame-180.jpg')),cv2.COLOR_BGR2RGB)
        empty=cv2.cvtColor(cv2.imread(str(ROOT/'empty-table-1.jpg')),cv2.COLOR_BGR2RGB)
        self.tracker.update(empty,100.3,frame_id=3)
        for i in range(4,8):self.tracker.update(moved,100+i*.1,frame_id=i)
        cards=self.visible(100.7)
        self.assertEqual({c['rank']+c['suit'] for c in cards if c['rank']},{'8♥','6♣'})
        self.assertTrue(all(c['identity_source']=='local_verified_face_match' for c in cards if c['rank']))
    def test_changed_pip_count_cannot_reuse_cached_rank(self):
        from card_tracking import pip_count
        t=next(t for t in self.tracker.tracks.values() if t.get('rank')=='8')
        patch=t['patch'].copy();self.assertEqual(pip_count(patch),8)
        # Remove a central pip: almost the same face must NOT inherit the 8 label.
        patch[14:25,8:18]=np.percentile(patch,80)
        self.assertNotEqual(pip_count(patch),8)
    def test_camera_restart_and_staleness_do_not_reuse_rank(self):
        self.assertFalse(self.tracker.snapshot(101)['fresh'])
        self.assertTrue(all(not c['visible'] for c in self.tracker.snapshot(101)['cards']))
        self.tracker.update(self.rgb,100.3,session='new-camera',frame_id=3)
        self.tracker.apply_read(self.read)
        self.assertTrue(all(not t.get('rank') for t in self.tracker.tracks.values()))
    def test_removed_card_does_not_survive_at_old_location(self):
        empty=cv2.cvtColor(cv2.imread(str(ROOT/'empty-table-1.jpg')),cv2.COLOR_BGR2RGB)
        self.tracker.update(empty,100.3,frame_id=3)
        self.assertEqual(self.visible(100.3),[])
    def test_slow_read_retains_capture_history_at_fifteen_hz(self):
        self.tracker=CardTracker()
        for i in range(276):self.tracker.update(self.rgb,100+i/15,frame_id=i)
        self.tracker.apply_read(self.read)
        self.assertEqual({c['rank'] for c in self.visible(100+275/15)},{'8','6','3'})
    def test_new_camera_session_may_reuse_previous_frame_number(self):
        self.tracker.update(self.rgb,100.3,session='replacement-session',frame_id=2)
        self.assertEqual(len(self.tracker.tracks),3)
        self.assertEqual(self.tracker.captured_at,100.3)
        self.assertFalse(any(t.get('rank') for t in self.tracker.tracks.values()))
    def test_uncertain_delayed_association_does_not_hide_visible_cards(self):
        from unittest.mock import patch
        with patch('card_tracking.similarity',return_value=0.0):self.tracker.apply_read(self.read)
        self.assertEqual(len(self.visible()),3)
        self.assertFalse(any(t.get('excluded') for t in self.tracker.tracks.values()))
    def test_cached_duplicate_examples_cannot_mask_a_competing_suit(self):
        entries=self.tracker.face_cache[('8','♥')]
        self.tracker.face_cache[('8','♥')]=entries*3
        self.tracker.face_cache[('8','♦')]=list(entries)
        hidden=self.rgb.copy();hidden[80:165,180:235]=[160,165,160]
        self.tracker.update(hidden,100.3,frame_id=3)
        self.tracker.update(self.rgb,100.4,frame_id=4)
        self.assertNotIn('8',[c['rank'] for c in self.visible(100.4)])
    def test_stale_result_does_not_label_current_position(self):
        self.tracker=CardTracker()
        self.tracker.update(self.rgb,110,frame_id=1)
        self.tracker.apply_read(self.read)
        self.assertTrue(all(not t.get('rank') for t in self.tracker.tracks.values()))

if __name__=='__main__':unittest.main()
