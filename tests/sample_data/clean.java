package demo;

/**
 * Clean, documented class with no smells.
 */
public class Calculator {

    /**
     * Add two integers.
     */
    public int add(int first, int second) {
        return first + second;
    }

    /**
     * Double a value.
     */
    public int twice(int value) {
        return add(value, value);
    }
}