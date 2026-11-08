import base64,tempfile,unittest
from top_camera import TopCameraReader,VisionError
class TopCameraTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.preview=lambda:{'images':[{'camera':'top','age_s':.1,'jpeg':base64.b64encode(b'\xff\xd8test').decode()}]}
        self.result={'cards':[{'rank':'A','suit':'diamonds','x':.5,'y':.25,'evidence':'A and diamond corner visible'}],'uncertain':False,'reason':'One readable card'}
        self.reader=TopCameraReader(preview=self.preview,judge=lambda p:self.result,directory=self.temp.name)
    def test_top_only_rank_and_suit(self):
        result=self.reader.scan();self.assertEqual(result['cards'][0]['rank'],'A');self.assertEqual(result['cards'][0]['suit'],'♦');self.assertEqual(result['camera'],'top')
    def test_uncertain_scene_never_invents_rank(self):
        self.result.update(cards=[],uncertain=True,reason='Arm occludes rank')
        result=self.reader.scan();self.assertTrue(result['uncertain']);self.assertEqual(result['cards'],[])
    def test_invalid_rank_rejected(self):
        self.result['cards'][0]['rank']='?'
        with self.assertRaises(VisionError):self.reader.scan()
    def test_duplicate_same_location_rejected(self):
        self.result['cards'].append(dict(self.result['cards'][0]))
        with self.assertRaises(VisionError):self.reader.scan()
    def test_stale_frame_rejected(self):
        p=self.preview();p['images'][0]['age_s']=2;self.reader.preview=lambda:p
        with self.assertRaises(VisionError):self.reader.scan()
    def test_missing_top_rejected(self):
        self.reader.preview=lambda:{'images':[]}
        with self.assertRaises(VisionError):self.reader.scan()
    def test_glare_reported_without_inventing_face(self):
        self.result['unreadable']=[{'x':.7,'y':.2,'cause':'glare','evidence':'Reflection hides both corner indices'}]
        output=self.reader.scan()
        self.assertTrue(output['uncertain']);self.assertEqual(output['unreadable'][0]['cause'],'glare')
        self.assertEqual(len(output['cards']),1)
    def test_occluded_card_remains_unknown(self):
        self.result.update(cards=[],unreadable=[{'x':.5,'y':.5,'cause':'occlusion','evidence':'Gripper covers the face'}])
        output=self.reader.scan();self.assertEqual(output['cards'],[]);self.assertTrue(output['uncertain'])
    def test_invalid_unreadable_coordinates_rejected(self):
        self.result['unreadable']=[{'x':2,'y':.2,'cause':'glare','evidence':'Reflection'}]
        with self.assertRaises(VisionError):self.reader.scan()
    def test_transfer_unknown_without_all_views(self):
        self.result['transfer']={'holder':'left','rank':'A','suit':'spades','rank_from_top':True,'evidence':'Card in left jaw'}
        output=self.reader.scan()
        self.assertEqual(output['transfer']['holder'],'unknown')
        self.assertIsNone(output['transfer']['rank'])
    def test_shared_grip_and_unreadable_face(self):
        data=self.preview();top=data['images'][0]
        data['images'] += [{**top,'camera':'left'},{**top,'camera':'right'}]
        data['measured']={'left':{'positions_rad':[0]*6,'gripper':.2,'ee_mm':[1,2,3]}}
        self.reader.preview=lambda:data
        self.result['transfer']={'holder':'both','rank':'A','suit':'spades','rank_from_top':False,'evidence':'Same card visibly retained by both jaws, back faces overhead'}
        output=self.reader.scan()
        self.assertEqual(output['transfer']['holder'],'both')
        self.assertIsNone(output['transfer']['rank'])
        self.assertEqual(output['measured']['left']['positions_rad'],[0]*6)
    def test_known_held_rank_requires_top(self):
        data=self.preview();top=data['images'][0];data['images'] += [{**top,'camera':'left'},{**top,'camera':'right'}]
        self.reader.preview=lambda:data
        self.result['transfer']={'holder':'right','rank':'7','suit':'diamonds','rank_from_top':True,'evidence':'7 diamond index clear in top; right alone holds'}
        output=self.reader.scan();self.assertEqual(output['transfer']['rank'],'7');self.assertEqual(output['transfer']['suit'],'♦')

if __name__=='__main__':unittest.main()
