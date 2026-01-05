class A:
    def on(self):
        print("A")


class B:
    def on(self):
        print("B")


class C(B, A):
    def on(self):
        super().on()
        print("C")


if __name__ == "__main__":
    C().on()
