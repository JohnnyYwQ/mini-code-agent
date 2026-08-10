class Memory:
    def __init__(self):
        """
        传入配置参数
            数据库路径
            向量库路径
            embedding模型
            reranker模型
        """

    def add(self):
        """
        添加memory进入数据库，然后同步到向量库，创建memory操作事件
        """

    def update(self):
        """
        更新数据库中数据，同步到向量库，创建memory操作事件
        """

    def get(self):
        """
        从数据库以及向量库取出memory
        """

    def delete(self):
        """
        从数据库删除memory，向量库也同步
        """

    def list(self):
        """
        列出数据库中的所有memory
        """

    def search(self):
        """
        查询数据库和向量库检索内容，包含rerank
        """
