#!/usr/bin/env python
import dist_test
import unittest

class TestTaskGroup(unittest.TestCase):

    def test_empty_task_status(self):
        tasks = []
        group = dist_test.TaskGroup(tasks)
        self.assertFalse(group.is_failed)
        self.assertFalse(group.is_flaky)
        self.assertFalse(group.is_succeeded)

if __name__ == "__main__":
    unittest.main()
