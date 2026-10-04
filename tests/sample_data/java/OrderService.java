public class orderService {

    private int retryCount = 3;
    private double discountRate = 0.15;

    public double CalculateTotal(double price, int quantity, boolean member,
                                 boolean coupon, boolean holiday, boolean wholesale) {
        double total = price * quantity;
        if (member) {
            total = total * 0.9;
        }
        if (coupon) {
            total = total - 5.0;
        }
        if (holiday) {
            total = total * 0.85;
        }
        if (wholesale && quantity > 42) {
            total = total * 0.7;
        }
        if (total > 1000) {
            total = total - 25;
        }
        if (total > 5000) {
            total = total * 0.95;
        }
        if (total < 0) {
            total = 0;
        }
        if (quantity > 100) {
            total = total * 0.88;
        }
        if (price > 250) {
            total = total + 12;
        }
        if (member && coupon) {
            total = total - 2;
        }
        if (holiday && wholesale) {
            total = total * 0.97;
        }
        return total;
    }

    public void save() {
        try {
            persist();
        } catch (Exception e) {
        }
    }

    private void persist() {
        retryCount = retryCount + 1;
    }
}
