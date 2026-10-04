import random
import unittest

from renderers.snake import plan_snake, SNAKE_LENGTH


class SnakePlannerTests(unittest.TestCase):
    def check_plan(self, columns, food):
        plan = plan_snake(columns, tuple(food))
        expected = {(x, y): level for x, y, level in food}
        self.assertEqual(len(plan.meals), len(expected))
        self.assertEqual({point for point, _ in plan.meals}, set(expected))
        self.assertEqual([expected[point] for point, _ in plan.meals], sorted(expected.values()))
        for point, step in plan.meals:
            self.assertEqual(plan.route[step], point)
            self.assertLess(step, len(plan.route) - 1)
        initial = [(-1, row) for row in range(SNAKE_LENGTH)]
        self.assertEqual(plan.route[0], (-1, 0))
        if food:
            self.assertEqual(plan.route[1], (0, 0))
        body = initial[:]
        # Verify adjacency, body collisions and the seam for two whole loops.
        for _ in range(2):
            for point in plan.route[1:]:
                self.assertEqual(abs(body[0][0]-point[0]) + abs(body[0][1]-point[1]), 1)
                self.assertNotIn(point, body[:-1])
                self.assertTrue(-1 <= point[0] < columns and 0 <= point[1] < 7)
                body = [point] + body[:-1]
            self.assertEqual(body, initial)
        return plan

    def test_empty_map_has_no_roaming_snake(self):
        plan = self.check_plan(53, [])
        self.assertEqual(len(plan.route), 1)

    def test_disconnected_levels_and_dense_maps(self):
        rng = random.Random(42)
        for columns in (1, 2, 52, 53, 54):
            for density in (.03, .4, 1):
                food = [(x, y, rng.randint(1, 4)) for x in range(columns) for y in range(7) if rng.random() < density]
                with self.subTest(columns=columns, density=density):
                    self.check_plan(columns, food)

    def test_higher_level_can_be_crossed_without_being_eaten(self):
        food = [(2, 0, 1)] + [(1, row, 4) for row in range(7)]
        plan = self.check_plan(3, food)
        first_meal_step = plan.meals[0][1]
        self.assertTrue(any(x == 1 for x, _ in plan.route[:first_meal_step]))
        self.assertEqual(plan.meals[0][0], (2, 0))

    def test_scattered_calendars_do_not_depend_on_input_order(self):
        for seed in range(12):
            rng = random.Random(seed)
            food = [(x, y, rng.randint(1, 4)) for x in range(53) for y in range(7) if rng.random() < .55]
            plan = self.check_plan(53, food)
            self.assertEqual(plan, plan_snake(53, tuple(reversed(food))))

    def test_invalid_coordinates_and_levels_are_rejected(self):
        for food in (((53, 0, 1),), ((0, 7, 1),), ((0, 0, 5),)):
            with self.assertRaises(ValueError):
                plan_snake(53, food)


if __name__ == '__main__':
    unittest.main()
