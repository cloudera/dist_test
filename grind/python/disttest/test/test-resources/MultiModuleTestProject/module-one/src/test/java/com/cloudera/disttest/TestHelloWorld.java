package com.cloudera.disttest;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

public class TestHelloWorld {

  @Test
  public void testHelloWorld() throws Exception {
    String[] files = {"/testresource1.txt", "/testresource2.txt"};
    StringBuilder builder = new StringBuilder();
    for (String file : files) {
      try (InputStream is = getClass().getResourceAsStream(file)) {
        BufferedReader reader = new BufferedReader(new InputStreamReader(is));
        while(reader.ready()) {
          builder.append(reader.readLine());
        }
      }
    }
    HelloWorld w = new HelloWorld();
    assertEquals(builder.toString(), w.toString());
  }
}
