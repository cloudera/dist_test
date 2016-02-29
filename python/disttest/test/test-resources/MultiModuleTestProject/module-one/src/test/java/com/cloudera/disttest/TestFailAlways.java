package com.cloudera.disttest;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.util.Random;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

public class TestFailAlways {

  @Test
  public void failSometimes() throws Exception {
    throw new Exception();
  }
}
