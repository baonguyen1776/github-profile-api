import random
import unittest

from renderers.snake import plan_snake, SNAKE_LENGTH


class SnakePlannerTests(unittest.TestCase):
    def check_plan(self, columns, food):
        plan = plan_snake(columns, tuple(food))
        expected = {(x, y): level for x, y, level in food}
        self.assertEqual(len(plan.meals), len(expected))
        self.assertEqual({point for point, _ in plan.meals}, set(expected))
        for point, step in plan.meals:
            self.assertEqual(plan.route[step], point)
            self.assertLess(step, len(plan.route) - 1)
        initial = [(-1, row) for row in range(SNAKE_LENGTH)]
        self.assertEqual(plan.route[0], (-1, 0))
        body = initial[:]
        # Verify adjacency, body collisions and the seam for two whole loops.
        for _ in range(2):
            for point in plan.route[1:]:
                self.assertEqual(abs(body[0][0]-point[0]) + abs(body[0][1]-point[1]), 1)
                self.assertNotIn(point, body[:-1])
                self.assertTrue(-1 <= point[0] <= columns and -1 <= point[1] <= 7)
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

    def test_higher_level_wall_is_bypassed_on_the_outer_lane(self):
        food = [(2, 3, 1)] + [(1, row, 4) for row in range(7)]
        plan = self.check_plan(3, food)
        first_meal_step = plan.meals[0][1]
        before_first_meal = plan.route[:first_meal_step]
        self.assertFalse(any(x == 1 and 0 <= y < 7 for x, y in before_first_meal))
        self.assertTrue(any(y in {-1, 7} for _, y in before_first_meal))
        self.assertEqual(plan.meals[0][0], (2, 3))

    def test_levels_are_ordered_when_lower_food_is_reachable(self):
        food = [(1, 1, 1), (3, 3, 1), (2, 5, 2), (4, 2, 3), (0, 6, 4)]
        plan = self.check_plan(6, food)
        levels = {(x, y): level for x, y, level in food}
        self.assertEqual([levels[point] for point, _ in plan.meals], [1, 1, 2, 3, 4])

    def test_enclosed_lower_level_opens_lowest_reachable_cell(self):
        food = [(1, 3, 1)] + [
            (x, y, 2)
            for x, y in ((0, 2), (1, 2), (2, 2), (0, 3), (2, 3), (0, 4), (1, 4), (2, 4))
        ]
        plan = self.check_plan(4, food)
        levels = {(x, y): level for x, y, level in food}
        eaten_levels = [levels[point] for point, _ in plan.meals]
        first_lower = eaten_levels.index(1)
        self.assertIn(2, eaten_levels[:first_lower])

    def test_route_never_steps_on_food_before_its_meal(self):
        food = [(2, 1, 1), (1, 3, 2), (3, 2, 3), (0, 5, 4)]
        plan = self.check_plan(5, food)
        meal_steps = {point: step for point, step in plan.meals}
        for step, point in enumerate(plan.route):
            if point in meal_steps:
                self.assertGreaterEqual(step, meal_steps[point])

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
