import unittest
from commands import parse,describe
class Commands(unittest.TestCase):
 def test_commands(self):
  for text,action in [('deal','deal'),('hit me','hit'),('stand','stand'),('double down','double'),('split','split')]:self.assertEqual(parse(text),{'action':action})
 def test_bets(self):
  for text,value in [('bet fifty',50),('bet 25 dollars',25),('please bet one hundred',100)]:self.assertEqual(parse(text),{'action':'bet','amount':value})
 def test_negation_and_robot_words_never_act(self):
  for text in ["don't hit",'do not deal','no hit','home arms','park','robot deal','bet 1000','bet five thousand','bet 5.5','hit then stand']:self.assertIsNone(parse(text),text)
 def test_whisper_style_transcripts(self):
  for text,action in [('Deal.','deal'),('Hit.','hit'),('Okay, hit me.','hit'),('Stand.','stand'),("I'll stand.",'stand'),('Double down.','double'),('Split, please.','split')]:self.assertEqual(parse(text),{'action':action},text)
  self.assertEqual(parse('Bet 25.'),{'action':'bet','amount':25});self.assertEqual(parse('Bet twenty-five.'),{'action':'bet','amount':25})
 def test_chatter_never_acts(self):
  for text in ['Thank you.','You.','Hit or stand?','Your move.','Dealer shows a nine.','Standing on sixteen.','Doubling down.','I think I should hit','']:self.assertIsNone(parse(text),text)
 def test_questions(self):self.assertEqual(parse('what do I have?')['action'],'hand');self.assertEqual(parse('how much do I have?')['action'],'bankroll')
if __name__=='__main__':unittest.main()
