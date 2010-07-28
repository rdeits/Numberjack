from Numberjack import *
import Mistral

# Create the model
model = Model()

#Variable definitions, we need a variable for every letter
s,m = (Variable(1,9) for val in range(2)) # These can't be zero as 
                                          # they are the start of a word
e,n,d,o,r,y = (Variable(0,9) for val in range(6)) # These can

model.add(      s*1000 + e*100 + n*10 + d +
                m*1000 + o*100 + r*10 + e ==
      m*10000 + o*1000 + n*100 + e*10 + y)

# Post the all different constraint on all the variables
model.add(AllDiff((s,e,n,d,m,o,r,y)))

# Load up model into solver
solver = Mistral.Solver(model)

# Now Solve
if solver.solve():
    print "   ", s,e,n,d
    print " + ", m,o,r,e
    print  "=", m,o,n,e,y

