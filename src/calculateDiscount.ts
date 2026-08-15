/**
 * Calculates the discount based on the price and percentage
 * @param price - The original price before discount
 * @param percentage - The discount percentage (0-100)
 * @returns The discounted amount
 */
function calculateDiscount(price: number, percentage: number): number {
    if (price < 0 || percentage < 0 || percentage > 100) {
        throw new Error("Invalid price or percentage");
    }

    return price * (percentage / 100);
}

export default calculateDiscount;

