/**
 * Calculates the final price after applying a discount.
 * @param price - The original price before discount
 * @param percentage - The discount percentage (0-100)
 * @returns The final price after the discount is applied
 */
function calculateDiscount(price: number, percentage: number): number {
    if (price < 0 || percentage < 0 || percentage > 100) {
        throw new Error("Invalid price or percentage");
    }

    return price - (price * percentage / 100);
}

export default calculateDiscount;

