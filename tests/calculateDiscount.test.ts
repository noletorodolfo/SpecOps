import calculateDiscount from '../src/calculateDiscount';

describe('calculateDiscount function', () => {
    test('should calculate the final price correctly for various scenarios', () => {
        expect(calculateDiscount(100, 10)).toBeCloseTo(90, 5);
        expect(calculateDiscount(250, 20)).toBeCloseTo(200, 5);
        expect(calculateDiscount(0, 5)).toBe(0);
        expect(calculateDiscount(150, 0)).toBe(150);
        expect(calculateDiscount(200, 100)).toBeCloseTo(0, 5);
    });

    test('should throw an error for invalid negative price', () => {
        expect(() => calculateDiscount(-100, 10)).toThrow("Invalid price or percentage");
    });

    test('should throw an error for invalid negative percentage', () => {
        expect(() => calculateDiscount(100, -10)).toThrow("Invalid price or percentage");
    });

    test('should throw an error for invalid percentage above 100', () => {
        expect(() => calculateDiscount(100, 110)).toThrow("Invalid price or percentage");
    });
});
