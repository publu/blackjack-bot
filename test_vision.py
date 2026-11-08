import base64
import copy
import tempfile
import unittest
from vision import CardReader, VisionError

class CardReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 100.0
        self.image = 1
        self.age = .1
        self.judgments = 0
        self.decision = {'verified': True, 'rank_from_top': True, 'rank': 'A', 'suit': 'spades',
            'exactly_one_new_card': True, 'face_up_on_table': True,
            'rank_and_suit_readable': True, 'existing_cards_unchanged': True,
            'evidence': 'The new card is face up on the table with A and spade visible.'}
        def preview():
            return {'images': [{'camera': c, 'age_s': self.age,
                'jpeg': base64.b64encode(b'\xff\xd8' + bytes([self.image]) * 100).decode()}
                for c in ('top', 'left', 'right')]}
        def judge(context, captures):
            self.judgments += 1
            self.assertEqual(context['task_id'], 'owned')
            self.assertEqual(len(captures), 2)
            return self.decision
        self.reader = CardReader(directory=self.tmp.name, preview=preview, judge=judge,
                                 clock=lambda: self.now)
        before = self.reader.capture()
        self.task = {'id': 'owned', 'status': 'done', 'created': 101,
            'card_cycle': {'id': 'owned', 'state': 'complete', 'slot_indices': [2], 'slot_index': 2},
            '_vision_before': before}
        self.now = 105
        self.image = 2

    def test_reads_paired_cameras_and_stable_id(self):
        result = self.reader.read(self.task)
        self.assertEqual((result['rank'], result['suit'], result['card_id']), ('A', '♠', 'owned:slot2'))
        self.assertEqual(self.reader.read(self.task), result)
        self.assertEqual(self.judgments, 1)

    def test_iso_task_created_supported(self):
        self.task['created'] = '1970-01-01T00:01:41Z'
        self.assertTrue(self.reader.read(self.task)['verified'])

    def test_numeric_cycle_created_preferred(self):
        self.task['created'] = 'invalid legacy string'
        self.task['card_cycle']['created'] = 101
        self.assertTrue(self.reader.read(self.task)['verified'])

    def test_mutating_baseline_is_rejected(self):
        self.task['_vision_before']['captured_at'] = 101
        with self.assertRaises(VisionError): self.reader.read(self.task)

    def test_failed_motion_is_not_verified(self):
        self.task['status'] = 'failed'
        with self.assertRaises(VisionError): self.reader.read(self.task)
        self.assertEqual(self.judgments, 0)

    def test_wrong_task_is_rejected(self):
        self.task['card_cycle']['id'] = 'other'
        with self.assertRaises(VisionError): self.reader.read(self.task)

    def test_batch_is_rejected(self):
        self.task['card_cycle']['slot_indices'] = [0, 1, 2]
        with self.assertRaises(VisionError): self.reader.read(self.task)

    def test_missing_baseline_is_rejected(self):
        self.task.pop('_vision_before')
        with self.assertRaises(VisionError): self.reader.read(self.task)

    def test_forged_baseline_is_rejected(self):
        self.task['_vision_before'] = copy.deepcopy(self.task['_vision_before'])
        self.task['_vision_before']['id'] = 'forged'
        with self.assertRaises(VisionError): self.reader.read(self.task)

    def test_stale_baseline_is_rejected(self):
        self.task['created'] = 120
        self.now = 125
        with self.assertRaises(VisionError): self.reader.read(self.task)

    def test_stale_after_frames_are_rejected(self):
        self.age = 1.0
        with self.assertRaises(VisionError): self.reader.read(self.task)

    def test_no_new_images_are_rejected(self):
        self.image = 1
        with self.assertRaises(VisionError): self.reader.read(self.task)

    def test_occlusion_and_ambiguity_fail_closed(self):
        for key in ('verified', 'rank_from_top', 'exactly_one_new_card', 'face_up_on_table',
                    'rank_and_suit_readable', 'existing_cards_unchanged'):
            self.decision[key] = False
            with self.assertRaises(VisionError): self.reader.read(self.task)
            self.decision[key] = True

    def test_invalid_rank_and_suit_fail_closed(self):
        self.decision['rank'] = 'maybe A'
        with self.assertRaises(VisionError): self.reader.read(self.task)
        self.decision['rank'] = 'A'; self.decision['suit'] = None
        with self.assertRaises(VisionError): self.reader.read(self.task)

    def test_missing_camera_fails_closed(self):
        self.reader.preview = lambda: {'images': []}
        with self.assertRaises(VisionError): self.reader.capture()

if __name__ == '__main__': unittest.main()
