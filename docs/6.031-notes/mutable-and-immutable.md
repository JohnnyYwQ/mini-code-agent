### Mutable and Immutable
## 可变变量
```typescript
array: number[] = [1, 2, 3];

let array2 = array;

此时array2也指向[1, 2, 3], 那array和array2改[1, 2, 3]中的元素两者会同步变化

若 array2 = [4, 5, 6]
不会让array和array2都指向[4, 5, 6]而是只让array2指向[4, 5, 6]
```
## 不可变变量

```typescript
let a:number = 5;
此时是a指向5

let b = a;
此时让b也指向5

b = 3;
此时让b指向3
```

## 可重新赋值
```typescript
let a = 3;
a = 4;

可重新赋值
```


## 不可重新赋值
```typescript
const a = 3;

此时a不能再重新赋值

readonly array = [1, 2, 3];

则让array不再能指向其他array

const readonly array = [1, 2, 3];

责让array既不能再指向其他array，也不能通过array修改内部的值，但是别的array一样可以指向[1, 2, 3]进而对其修改
```