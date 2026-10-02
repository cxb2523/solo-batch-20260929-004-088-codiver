package demo;

/**
 * A deliberately problematic class used to exercise many detectors at once.
 */
public class GodClass {
    private int a; private int b; private int c; private int d;
    private int e; private int f; private int g; private int h;
    private int i; private int j; private int k; private int l;
    private int m; private int n; private int o; private int p;

    public GodClass() {}
    public void processData(int p1, int p2, int p3, int p4, int p5, int p6) {
        int x = 10;
        int y = 20;
        int z = 30;
        int q = 40;
        if (x > 0) {
            if (y > 0) {
                if (z > 0) {
                    if (q > 0) {
                        if (x == y) {
                            x = y + z + q + 50;
                        }
                    }
                }
            }
        }
        try {
            x = x / y;
        } catch (ArithmeticException ex) {
        }
    }

    public void getA() {}
    public void setA(int v) {}
}