Entendido. Criaremos uma função simples em TypeScript chamada `calculateDiscount` para calcular o desconto sobre um preço dado uma porcentagem. Considerando a profundidade dessa funcionalidade, não será necessário quebrá-la em múltiplos domínios, bounded contexts ou business capabilities. Ela será tratada como uma capacidade de negócios que está diretamente ligada à lógica de preços e promoções.

### Função `calculateDiscount`

```typescript
// Function to calculate discount
function calculateDiscount(price: number, percentage: number): number {
    if (price < 0 || percentage < 0 || percentage > 100) {
        throw new Error("Invalid price or percentage");
    }
    return price * (percentage / 100);
}

export default calculateDiscount;
```

### Testes Unitários

Usaremos a biblioteca Jest para escrever os testes unitários.

Primeiro, instale o Jest se você ainda não o tiver:

```bash
npm install --save-dev jest @types/jest ts-jest
```

Depois, configure o Jest para entender arquivos TypeScript.

Crie um arquivo `jest.config.js` com o seguinte conteúdo:

```js
module.exports = {
    preset: 'ts-jest',
    testEnvironment: 'node',
};
```

Agora, crie um arquivo de teste chamado `calculateDiscount.test.ts` na mesma pasta da função:

```typescript
import calculateDiscount from './calculateDiscount';

describe('calculateDiscount function', () => {
    test('should calculate the discount correctly', () => {
        expect(calculateDiscount(100, 10)).toBe(10);
        expect(calculateDiscount(250, 20)).toBe(50);
        expect(calculateDiscount(0, 5)).toBe(0);
        expect(calculateDiscount(150, 0)).toBe(0);
    });

    test('should return 0 when no percentage is provided', () => {
        expect(calculateDiscount(100, 0)).toBe(0);
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
```

Em seguida, adicione um script no seu `package.json` para rodar os testes:

```json
"scripts": {
    "test": "jest"
}
```

### Executando os Testes

Para executar os testes, basta rodar o comando:

```bash
npm test
```

## Resumo

Essa função e esses testes correspondem a uma única capacidade de negócios: o cálculo do desconto sobre um preço. Não há necessidade de modelar esse tipo de funcionalidade trivial em vários domínios ou contexts, já que ela é focada em um único aspecto do negócio.