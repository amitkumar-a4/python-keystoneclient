all: trilio-vix-disk-cli

clean:
	$(RM) -f trilio-vix-disk-cli

trilio-vix-disk-cli: trilio-vix-disk-cli.cpp
	$(CXX) -v -I/usr/lib/vmware-vix-disklib/include  -L/usr/lib/vmware-vix-disklib/lib64  -march=x86-64 $? -lvixDiskLib -o $@

