package com.cloudera.disttest;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public class TestLinkedListReversal {
  
  public static Node createList() {
    Node head = null;
    for (int i=10; i>=1; i--) {
      Node newHead = new Node();
      newHead.value = i;
      newHead.next = head;
      head = newHead;
    }
    return head;
  }

  public static boolean isAscending(Node head) {
    int last = Integer.MIN_VALUE;
    while (head != null) {
      if (last > head.value) {
        return false;
      }
      last = head.value;
      head = head.next;
    }
    return true;
  }
  
  public static boolean isDescending(Node head) {
    int last = Integer.MAX_VALUE;
    while (head != null) {
      if (last < head.value) {
        return false;
      }
      last = head.value;
      head = head.next;
    }
    return true;
  }

  public static int countNodes(Node head) {
    int count = 0;
    while (head != null) {
      count++;
      head = head.next;
    }
    return count;
  }

  @Test
  public void testReversal() throws Exception {
    Node list = createList();
    LinkedListReversal.printList(list);
    assertTrue(isAscending(list));
    int count = countNodes(list);

    list = LinkedListReversal.reverse(list);
    LinkedListReversal.printList(list);
    assertTrue(isDescending(list));
    assertEquals(count, countNodes(list));
  }
}
