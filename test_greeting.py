import unittest
from greeting import greet

class TestGreetingFunction(unittest.TestCase):

    def test_greet_with_valid_name(self):
        result = greet('Alice')
        self.assertEqual(result, 'Olá, Alice!')

    def test_greet_with_another_valid_name(self):
        result = greet('Bob')
        self.assertEqual(result, 'Olá, Bob!')

    def test_greet_with_empty_string(self):
        with self.assertRaises(ValueError):
            greet('')

    def test_greet_with_invalid_type(self):
        with self.assertRaises(ValueError):
            greet(123)

    def test_greet_with_whitespace(self):
        with self.assertRaises(ValueError):
            greet('   ')

if __name__ == '__main__':
    unittest.main()
