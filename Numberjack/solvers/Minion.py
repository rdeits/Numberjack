from Numberjack.ExternalSolver import ExternalSolver
from Numberjack import NBJ_STD_Solver, Variable, SAT, UNSAT
import sys
import re


class Minion_Expression(object):

    def __init__(self, *args):
        self.nbj_ident = None
        self.varname = None
        self.solver = None
        self.lb = self.ub = None

    def add(self, solver, toplevel):
        pass

    def has_been_added(self):
        return self.solver is not None

    def get_min(self):
        return self.lb

    def get_max(self):
        return self.ub

    def get_size(self):
        return self.ub - self.lb + 1


class Minion_IntVar(Minion_Expression):

    def __init__(self, *args):
        super(Minion_IntVar, self).__init__()
        # print "IntVar", len(args), repr(args)
        self.domain = self.value = None

        if len(args) == 0:  # Boolean
            self.lb, self.ub = 0, 1
        elif len(args) == 3:
            self.lb, self.ub, self.nbj_ident = args
        elif len(args) == 2:
            if hasattr(args[0], "__iter__"):
                self.domain, self.nbj_ident = args
            else:
                self.lb, self.ub = args
                self.nbj_ident = -1
        else:
            raise Exception("Unknown constructor for %s" % str(type(self)))

    def add(self, solver, toplevel):
        if self.lb == self.ub:
            self.value = self.lb
            return str(self.lb)

        if not self.has_been_added():
            self.varname = "x%d" % (solver.variablecount)  # Minion variable name
            solver.variablecount += 1
            self.solver = solver

            if self.lb == 0 and self.ub == 1:
                solver.create_variable(self, self.varname, "BOOL %s" % self.varname)
            elif self.domain and len(self.domain) != (self.ub - self.lb) + 1:
                dom_str = csvstr(map(str, self.domain))
                solver.create_variable(self, self.varname, "SPARSEBOUND %s {%s}" % (self.varname, dom_str))
            else:
                solver.create_variable(self, self.varname, "DISCRETE %s {%d..%d}" % (self.varname, self.lb, self.ub))
        return self

    def get_value(self):
        return self.value


class MinionIntArray(list):
    add = list.append
    size = list.__len__


class MinionExpArray(list):
    add = list.append
    size = list.__len__


class Minion_binop(Minion_Expression):

    def __init__(self, arg1, arg2):
        super(Minion_binop, self).__init__()
        self.vars = [arg1, arg2]
        self.lb, self.ub = 0, 1

    def add(self, solver, toplevel):
        if not self.has_been_added():
            self.solver = solver
            self.vars[0] = self.vars[0].add(solver, False)
            if isinstance(self.vars[1], Minion_Expression):
                self.vars[1] = self.vars[1].add(solver, False)
            if not toplevel:
                self.auxvar = Minion_IntVar().add(solver, False)
                self.varname = varname(self.auxvar)
        return self


class Minion_ne(Minion_binop):

    def add(self, solver, toplevel):
        if not self.has_been_added():
            super(Minion_ne, self).add(solver, toplevel)
            solver.print_constraint("diseq(%s, %s)" % (varname(self.vars[0]), varname(self.vars[1])))
        return self


class Minion_eq(Minion_binop):

    def add(self, solver, toplevel):
        if not self.has_been_added():
            assert toplevel, "Constraint not implemented as a sub-expression/reified yet."
            super(Minion_eq, self).add(solver, toplevel)
            solver.print_constraint("eq(%s, %s)" % (varname(self.vars[0]), varname(self.vars[1])))
        return self


class Minion_lt(Minion_binop):

    def add(self, solver, toplevel):
        if not self.has_been_added():
            assert toplevel, "Constraint not implemented as a sub-expression/reified yet."
            super(Minion_lt, self).add(solver, toplevel)
            consstr = "ineq(%s, %s, -1)" % (varname(self.vars[0]), varname(self.vars[1]))
            if toplevel:
                solver.print_constraint(consstr)
            else:
                solver.print_constraint("reify(%s, %s)" % (consstr, varname(self)))
        return self


class Minion_le(Minion_binop):

    def add(self, solver, toplevel):
        if not self.has_been_added():
            super(Minion_le, self).add(solver, toplevel)
            consstr = "ineq(%s, %s, 0)" % (varname(self.vars[0]), varname(self.vars[1]))
            if toplevel:
                solver.print_constraint(consstr)
            else:
                solver.print_constraint("reify(%s, %s)" % (consstr, varname(self)))
        return self


class Minion_gt(Minion_binop):

    def add(self, solver, toplevel):
        if not self.has_been_added():
            super(Minion_gt, self).add(solver, toplevel)
            consstr = "ineq(%s, %s, -1)" % (varname(self.vars[1]), varname(self.vars[0]))
            if toplevel:
                solver.print_constraint(consstr)
            else:
                solver.print_constraint("reify(%s, %s)" % (consstr, varname(self)))
        return self


class Minion_ge(Minion_binop):

    def add(self, solver, toplevel):
        if not self.has_been_added():
            super(Minion_ge, self).add(solver, toplevel)
            consstr = "ineq(%s, %s, 0)" % (varname(self.vars[1]), varname(self.vars[0]))
            if toplevel:
                solver.print_constraint(consstr)
            else:
                solver.print_constraint("reify(%s, %s)" % (consstr, varname(self)))
        return self


class Minion_or(Minion_binop):

    def add(self, solver, toplevel):
        if not self.has_been_added():
            assert toplevel, "Constraint not implemented as a sub-expression/reified yet."
            super(Minion_or, self).add(solver, toplevel)

            # watched-or requires the constraints to be specified in brackets,
            # possible to change to this later? for now decompose to
            # Sum(reified variables) >= 1
            s = Minion_Sum(self.vars)
            return Minion_ge(s, 1).add(solver, toplevel)

        return self


class Minion_mul(Minion_Expression):

    def __init__(self, var1, var2):
        super(Minion_mul, self).__init__()
        self.vars = [var1, var2]
        l1, u1 = var1.get_min(), var1.get_max()

        if isinstance(var2, Minion_Expression):
            l2, u2 = var2.get_min(), var2.get_max()
        else:
            if not isinstance(var2, int):
                raise Exception("Multiplication must be either by an expression or int, got '%s'." % str(type(var2)))
            l2 = u2 = var2

        self.lb = min(l1 * l2, l1 * u2, u1 * l2, u1 * u2)
        self.ub = max(l1 * l2, l1 * u2, u1 * l2, u1 * u2)

    def add(self, solver, toplevel):
        assert not toplevel, "Constraint is only valid as a sub-expression."
        if not self.has_been_added():
            super(Minion_mul, self).add(solver, toplevel)
            self.auxvar = Minion_IntVar(self.lb, self.ub).add(solver, False)
            self.varname = varname(self.auxvar)
            print "Adding mul", self.lb, self.ub, self.varname
            solver.print_constraint("product(%s, %s, %s)" % (varname(self.vars[0]), varname(self.vars[1]), varname(self)))
        return self


class Minion_AllDiff(Minion_Expression):

    def __init__(self, *args):
        super(Minion_AllDiff, self).__init__()
        if len(args) == 1:
            self.vars = args[0]
        elif len(args) == 2:
            self.vars = [args[0], args[1]]

    def add(self, solver, toplevel):
        if not self.has_been_added():
            super(Minion_AllDiff, self).add(solver, toplevel)
            for i in xrange(len(self.vars)):
                if isinstance(self.vars[i], Minion_Expression):
                    self.vars[i] = self.vars[i].add(solver, False)

            if len(self.vars) == 1:  # Just return the variable
                return self.vars[0]
            elif len(self.vars) == 2:
                # Replace a binary alldiff with a disequality
                ne = Minion_ne(*self.vars)
                return ne.add(solver, toplevel)
            else:
                assert toplevel, "Constraint not implemented as a sub-expression/reified yet."

                solver.print_constraint("gacalldiff([%s])" % (csvstr(map(varname, self.vars))))
        return self


class Minion_LeqLex(Minion_Expression):

    def __init__(self, children):
        self.vars = children
        super(Minion_LeqLex, self).__init__()

    def add(self, solver, toplevel):
        if not self.has_been_added():
            super(Minion_LeqLex, self).add(solver, toplevel)
            for i in xrange(len(self.vars)):
                self.vars[i] = self.vars[i].add(solver, False)

            assert toplevel, "Constraint not implemented as a sub-expression/reified yet."
            names = [varname(x) for x in self.vars]
            solver.print_constraint(
                "lexleq([%s], [%s])" %
                (csvstr(names[:len(names)/2]), csvstr(names[len(names)/2:])))
        return self


class Minion_LessLex(Minion_Expression):

    def __init__(self, children):
        self.vars = children
        super(Minion_LessLex, self).__init__()

    def add(self, solver, toplevel):
        if not self.has_been_added():
            super(Minion_LessLex, self).add(solver, toplevel)
            for i in xrange(len(self.vars)):
                self.vars[i] = self.vars[i].add(solver, False)

            assert toplevel, "Constraint not implemented as a sub-expression/reified yet."
            names = [varname(x) for x in self.vars]
            solver.print_constraint(
                "lexless([%s], [%s])" %
                (csvstr(names[:len(names)/2]), csvstr(names[len(names)/2:])))
        return self


class Minion_Gcc(Minion_Expression):

    def __init__(self, children, vals, lb_card, ub_card):
        self.vars = children
        self.vals = vals
        self.lb_card = lb_card
        self.ub_card = ub_card
        super(Minion_Gcc, self).__init__()

    def add(self, solver, toplevel):
        if not self.has_been_added():
            super(Minion_Gcc, self).add(solver, toplevel)
            for i in xrange(len(self.vars)):
                self.vars[i] = self.vars[i].add(solver, False)

            assert toplevel, "Constraint not implemented as a sub-expression/reified yet."
            names = [varname(x) for x in self.vars]
            value_str = csvstr(self.vals)
            auxvariables = [Minion_IntVar(l, u) for l, u in zip(self.lb_card, self.ub_card)]
            for i in xrange(len(auxvariables)):
                auxvariables[i] = auxvariables[i].add(solver, False)
            vec_str = csvstr(map(varname, auxvariables))
            solver.print_constraint("gccweak([%s], [%s], [%s])" %
                                    (csvstr(names), value_str, vec_str))
        return self


class Minion_Sum(Minion_Expression):

    def __init__(self, *args):
        super(Minion_Sum, self).__init__()
        self.offset = 0
        self.weights = None
        self.auxvar = None
        print "SUM:", len(args)
        if len(args) >= 1 and len(args) <= 3:
            if hasattr(args[0], '__iter__'):
                self.vars = args[0]
            else:
                self.vars = [args[0]]

            if len(args) >= 2:
                self.weights = args[1]

            if len(args) == 3:
                self.offset = args[2]

        elif len(args) == 4:
            self.vars = [args[0], args[1]]
            self.weights = args[2]
            self.offset = args[3]

        else:
            raise Exception("Invalid constructor to Minion_Sum args: %s" % str(args))

        if self.weights:
            self.lb = sum(w * x.get_min() if w >= 0 else w * x.get_max() for w, x in zip(self.weights, self.vars)) + self.offset
            self.ub = sum(w * x.get_max() if w >= 0 else w * x.get_min() for w, x in zip(self.weights, self.vars)) + self.offset
        else:
            print "VARS:", self.vars
            self.lb = sum(x.get_min() for x in self.vars) + self.offset
            self.ub = sum(x.get_max() for x in self.vars) + self.offset

    def add(self, solver, toplevel):
        assert not toplevel, "Constraint is only valid as a sub-expression."
        if not self.has_been_added():
            super(Minion_Sum, self).add(solver, toplevel)
            for i in xrange(len(self.vars)):
                self.vars[i] = self.vars[i].add(solver, False)

            if len(self.vars) == 1 and self.offset == 0:
                return self.vars[0]

            names = [varname(x) for x in self.vars]
            self.auxvar = Minion_IntVar(self.lb, self.ub).add(solver, False)
            self.varname = varname(self.auxvar)

            # print "Sum", len(self.vars), self.vars, self.offset
            if self.offset != 0:
                if len(self.vars) == 1:
                    solver.print_constraint("ineq(%s, %s, %d)" % (varname(self), names[0], self.offset))
                    solver.print_constraint("ineq(%s, %s, %d)" % (names[0], varname(self), -self.offset))
                    return self.auxvar
                else:
                    print >> sys.stderr, "Error: translation of Sum with multiple variables and an offset not implemented yet."
                    print >> sys.stderr, self.offset, self.weights, names
                    sys.exit(1)
            else:
                varvecstr = csvstr(names)
                if self.weights and any(x != 1 for x in self.weights):  # Weighted
                    constantvecstr = csvstr(self.weights)
                    solver.print_constraint("weightedsumgeq([%s], [%s], %s)" % (constantvecstr, varvecstr, varname(self)))
                    solver.print_constraint("weightedsumleq([%s], [%s], %s)" % (constantvecstr, varvecstr, varname(self)))
                else:  # Unweighted FIXME test
                    solver.print_constraint("sumgeq([%s], %s)" % (varvecstr, varname(self)))
                    solver.print_constraint("sumleq([%s], %s)" % (varvecstr, varname(self)))
            return self.auxvar

        return self

    def get_value(self):
        return self.auxvar.get_value()


class Minion_Minimise(Minion_Expression):

    def __init__(self, var):
        super(Minion_Minimise, self).__init__()
        self.var = var

    def add(self, solver, toplevel):
        assert toplevel, "Constraint is not valid as a sub-expression."
        if not self.has_been_added():
            super(Minion_Minimise, self).add(solver, toplevel)
            self.var = self.var.add(solver, False)
            solver.print_search("MINIMISING %s" % varname(self.var))
        return self


class Minion_Maximise(Minion_Expression):

    def __init__(self, var):
        super(Minion_Maximise, self).__init__()
        self.var = var

    def add(self, solver, toplevel):
        assert toplevel, "Constraint is not valid as a sub-expression."
        if not self.has_been_added():
            super(Minion_Maximise, self).add(solver, toplevel)
            self.var = self.var.add(solver, False)
            solver.print_search("MAXIMISING %s" % varname(self.var))
        return self


# class ExternalIntVariable(object):

#     def __init__(self, nj_var):
#         self.nj_var = nj_var
#         self.value = None

#     def get_value(self):
#         # print "Get value", self.nj_var.name()
#         return self.value

#     def get_min(self):
#         return self.nj_var.lb
#     #     return self.nj_var.get_min(solver=None)

#     def get_max(self):
#         return self.nj_var.ub
#     #     return self.nj_var.get_max(solver=None)

#     def get_size(self):
#         return self.get_max() - self.get_min() + 1


class MinionSolver(ExternalSolver):

    HEADER, VARIABLES, CONSTRAINTS, SEARCH = 0, 1, 2, 3

    def __init__(self):
        super(MinionSolver, self).__init__()
        self.solverexec = "minion"
        self.name_var_map = {}  # Maps an output variable name back to the Variable object
        self.last_section = MinionSolver.HEADER
        self.variablecount = self.constraintcount = 0

        self.info_regexps = {  # See doc on ExternalSolver.info_regexps
            'nodes': (re.compile(r'^Nodes:[ ]+(?P<nodes>\d+)$'), int),
            'time': (re.compile(r'^Solve Time:[ ]+(?P<time>\d+\.\d+)$'), float),
            # 'failures': (re.compile(r'^conflicts[ ]+:[ ]+(?P<failures>\d+)[ ]'), int),
        }
        self.f = open(self.filename, "wt")
        print >> self.f, "MINION 3"

    def build_solver_cmd(self):
        # The Verbosity that we pass down to the solver should be at least 1 so
        # that we can parse information like number of nodes, failures, etc.
        return "%(solverexec)s %(filename)s" % vars(self)

    def add(self, expr):
        # print "Solver add"
        # print type(expr), str(expr)
        expr.add(self, True)

    def initialise(self, searchvars=None):
        print "initialise", str(searchvars)
        pass  # FIXME, could add the search vars

    def solve(self, *args, **kwargs):
        print >> self.f, "**EOF**"
        print "calling solve"
        self.f.close()

        # DEBUG
        with open(self.filename, "rt") as f:
            for line in f:
                print line,

        return super(MinionSolver, self).solve(*args, **kwargs)

    def create_variable(self, localvarobj, name, s):
        self.name_var_map[name] = localvarobj
        self.print_variable(s)

    def print_variable(self, s):
        if self.last_section != MinionSolver.VARIABLES:
            self.last_section = MinionSolver.VARIABLES
            print >> self.f, "**VARIABLES**"  # FIXME switching back and forth
        print >> self.f, s

    def print_constraint(self, s):
        if self.last_section != MinionSolver.CONSTRAINTS:
            self.last_section = MinionSolver.CONSTRAINTS
            print >> self.f, "**CONSTRAINTS**"
        self.constraintcount += 1
        print >> self.f, s

    def print_search(self, s):
        if self.last_section != MinionSolver.SEARCH:
            self.last_section = MinionSolver.SEARCH
            print >> self.f, "**SEARCH**"
        print >> self.f, s

    def getNumVariables(self):
        return self.variablecount

    def getNumConstraints(self):
        return self.constraintcount

    # def create_variable(self, f, lb, ub, domain=None, v=None):
    #     name = "x%d" % (self.variable_id)  # Minion variable name
    #     self.variable_id += 1
    #     if v:
    #         # Create a wrapper variable that numberjack will call get_value on
    #         # which will be associated with the Minion variable
    #         # my_var = ExternalIntVariable()
    #         my_var = ExternalIntVariable(v)
    #         v.setVar(self.solver_id, self.solver_name, my_var, new_solver=self)
    #         v.solver = self

    #         self.name_var_map[name] = my_var
    #         self.expr_name_map[v] = name

    #     if lb == ub:
    #         return str(lb)
    #     elif lb == 0 and ub == 1:
    #         self.print_variable(f, "BOOL %s" % name)
    #     elif domain and len(domain) != (ub - lb) + 1:
    #         dom_str = ",".join(str(x) for x in domain)
    #         self.print_variable(f, "SPARSEBOUND %s {%s}" % (name, dom_str))
    #     else:
    #         self.print_variable(f, "DISCRETE %s {%d..%d}" % (name, lb, ub))
    #     return name

    # def create_aux_variable(self, f, expr):
    #     print "# creating aux variable for", str(expr)
    #     return self.create_variable(f, expr.lb, expr.ub, v=expr)

    # def output_variable(self, f, v):
    #     return self.create_variable(f, v.lb, v.ub, domain=v.domain_, v=v)

    # def output_variables(self, f):
    #     for v in self.model.variables:
    #         self.output_variable(f, v)

    # def output_constraints(self, f):
    #     for c in self.model.get_exprs():
    #         self.output_expr(f, c, toplevel=True)

    # def output_expr(self, f, e, toplevel=True):
    #     """"
    #         Outputs the expression 'e' to minion format. If toplevel is False
    #         then will reify the expression and return the name of the
    #         auxiliary Boolean variable that it was reified to.
    #     """
    #     def getchildname(x):
    #         # print "# getchildname", type(x), str(x)
    #         if type(x) in [int]:
    #             return str(x)
    #         elif isinstance(x, Variable):
    #             # Return the minion name for this variable
    #             return self.expr_name_map[x]
    #         else:
    #             return self.output_expr(f, x, toplevel=False)
    #             # print >> sys.stderr, "Error need to get the reified version of this constraint."
    #             # sys.exit(1)

    #     op = e.get_operator()
    #     print "# op:", op, toplevel, "e:", e, "children:", e.children
    #     names = [getchildname(child) for child in e.children]
    #     print "#", names

    #     # -------------------- Top level constraints --------------------
    #     if toplevel:

    #         if op == "ne":
    #             self.print_constraint(f, "diseq(%s, %s)" % tuple(names))

    #         elif op == "eq":
    #             self.print_constraint(f, "eq(%s, %s)" % tuple(names))

    #         elif op == "lt":
    #             self.print_constraint(f, "ineq(%s, %s, -1)" % tuple(names))

    #         elif op == "le":
    #             self.print_constraint(f, "ineq(%s, %s, 0)" % tuple(names))

    #         elif op == "gt":
    #             self.print_constraint(f, "ineq(%s, %s, -1)" % (names[1], names[0]))

    #         elif op == "ge":
    #             self.print_constraint(f, "ineq(%s, %s, 0)" % (names[1], names[0]))

    #         elif op == "AllDiff":
    #             self.print_constraint(f, "gacalldiff([%s])" % (csvstr(names)))

    #         elif op == "LeqLex":
    #             self.print_constraint(f, "lexleq([%s], [%s])" % (csvstr(names[:len(names)/2]), csvstr(names[len(names)/2:])))

    #         elif op == "LessLex":
    #             self.print_constraint(f, "lexless([%s], [%s])" % (csvstr(names[:len(names)/2]), csvstr(names[len(names)/2:])))

    #         elif op == "Gcc":
    #             print "# Gcc Parameters:", e.parameters
    #             value_str = csvstr(e.parameters[0])
    #             vec_str = csvstr(self.create_variable(f, l, u) for l, u in zip(e.parameters[1], e.parameters[2]))
    #             self.print_constraint(f, "gccweak([%s], [%s], [%s])" % (csvstr(names), value_str, vec_str))

    #         else:
    #             print >> sys.stderr, "# UNKNOWN top level constraint", op, c
    #             sys.exit(1)

    #     # -------------------- Sub-expressions --------------------
    #     else:
    #         aux_name = self.create_aux_variable(f, e)
    #         if op == "Abs":
    #             self.print_constraint(f, "abs(%s, %s)" % (aux_name, names[0]))

    #         elif op == "div":
    #             self.print_constraint(f, "div(%s, %s, %s)" % (names[0], names[1], aux_name))

    #         elif op == "Element":
    #             self.print_constraint(f, "element([%s], %s, %s)" % (csvstr(names[:-1]), names[-1], aux_name))

    #         elif op == "Sum":
    #             flat_coefs, offset = e.parameters

    #             if offset != 0:
    #                 assert(len(names) == 1, "asdf")  # FIXME
    #                 self.print_constraint(f, "ineq(%s, %s, %d)" % (aux_name, names[0], offset))
    #                 self.print_constraint(f, "ineq(%s, %s, %d)" % (names[0], aux_name, -offset))
    #                 print >> sys.stderr, "Error: translation of Sum with offset not implemented yet."
    #                 print >> sys.stderr, offset, flat_coefs, names
    #                 sys.exit(1)

    #             constantvecstr = csvstr(flat_coefs)
    #             varvecstr = csvstr(names)
    #             if any(lambda x: x != 1 for x in flat_coefs):  # Weighted
    #                 self.print_constraint(f, "weightedsumgeq([%s], [%s], %s)" % (constantvecstr, varvecstr, aux_name))
    #                 self.print_constraint(f, "weightedsumleq([%s], [%s], %s)" % (constantvecstr, varvecstr, aux_name))
    #             else:  # Unweighted FIXME test
    #                 self.print_constraint(f, "sumgeq([%s], %s)" % (varvecstr, aux_name))
    #                 self.print_constraint(f, "sumleq([%s], %s)" % (varvecstr, aux_name))

    #         else:
    #             print >> sys.stderr, "# UNKNOWN sub-expression", op, e
    #             sys.exit(1)
    #         return aux_name

    #     return None

    def parse_output(self, output):
        print "c Parse output"
        minionvarid = 0
        # Assumes variables are printed in the order x1, x2, ...
        for line in output.split("\n"):
            line = line.strip()
            # print repr(line)
            if line.startswith("Sol: "):
                name = "x%d" % (minionvarid)  # Minion variable name
                minionvarid += 1
                val = int(line.split(" ")[-1])
                # print "setting %s to %d" % (name, val)
                assert name in self.name_var_map, "Unknown variable in solver's output %s" % varname
                self.name_var_map[name].value = val

            elif line.startswith("Solutions Found: "):
                sols = int(line.split(" ")[-1])
                if sols > 0:
                    self.sat = SAT
            elif line.startswith("Problem solvable?: "):
                if line.endswith(" no"):
                    self.sat = UNSAT

            elif line.startswith("Solution Number: "):
                minionvarid = 0  # Reset variable counter for the next solution

            else:
                self.parse_solver_info_line(line)


def csvstr(l):
    return ",".join(str(v) for v in l)


def varname(x):
    if isinstance(x, Minion_Expression):
        assert x.varname is not None, "Error varname not set %s %s" % (str(x), str(x.nbj_ident))
        return x.varname
    return str(x)


class Solver(NBJ_STD_Solver):
    def __init__(self, model=None, X=None, FD=False, clause_limit=-1, encoding=None):
        NBJ_STD_Solver.__init__(self, "Minion", "Minion", model, X, FD, clause_limit, encoding)
