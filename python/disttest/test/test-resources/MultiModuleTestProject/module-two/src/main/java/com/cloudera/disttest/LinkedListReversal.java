package com.cloudera.disttest;

public class LinkedListReversal {
  
  public static Node reverse(Node head) {
    if (head == null || head.next == null) {
      return head;
    }
    Node prev = null;
    Node cur = head;
    while (cur != null) {
      Node next = cur.next;
      cur.next = prev;
      prev = cur;
      cur = next;
    }
    return prev;
  }

  public static void printList(Node head) {
    Node cur = head;
    while (cur != null) {
      System.out.print(cur.value + " -> ");
      cur = cur.next;
    }
    System.out.println("null");
  }
}
