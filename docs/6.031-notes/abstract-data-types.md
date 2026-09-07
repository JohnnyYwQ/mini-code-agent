### Abstract Data Types(ADT)

ADT就是由spec + operations各自的spec共同定义，由implementation来具体实现

## Operations

- creator: 一般是实例的初始化

- producer: 对实例的处理，一般参数包含实例本身，不修改原对象

- observer: 观察实例的特性吧，取实例的特性，一般不修改原对象

- mutator: 改变实例的中一些特性的值，修改原对象

## Independent

class追求一个表示独立，即外部客户端再调用一些operation的时候，不需要依赖class的内部表示，即class内部怎么改，客户端的代码都不用改，此为独立。

## Good ADT

一个好的 ADT 应该：

1. simple：操作少而简单，不要堆很多复杂方法。

2. coherent：每个操作目的明确，行为连贯，不要混很多特殊情况。

3. adequate：操作足够用，client 能方便拿到需要的基本信息。

4. representation independent：外部不依赖内部表示，内部实现可替换。