package com.cloudera.disttest;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.util.Random;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

public class TestFailSometimes {

  @Test
  public void failSometimes() throws Exception {
    Random r = new Random();
    if (r.nextFloat() > 0.5) {
      throw new Exception();
    }
  }
}
