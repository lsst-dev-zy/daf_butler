# This file is part of daf_butler.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Syntax definition for user expression parser.
"""

__all__ = ["ParserYacc", "ParserYaccError", "ParseError", "ParserEOFError"]

# -------------------------------
#  Imports of standard modules --
# -------------------------------

# -----------------------------
#  Imports for other modules --
# -----------------------------
from .exprTree import (BinaryOp, Identifier, IsIn, NumericLiteral,
                       Parens, StringLiteral, UnaryOp)
from .ply import yacc
from .parserLex import ParserLex

# ----------------------------------
#  Local non-exported definitions --
# ----------------------------------

# ------------------------
#  Exported definitions --
# ------------------------


class ParserYaccError(Exception):
    """Base class for exceptions generated by parser.
    """
    pass


class ParseError(ParserYaccError):
    """Exception raised for parsing errors.

    Attributes
    ----------
    expression : str
        Full initial expression being parsed
    token : str
        Current token at parsing position
    pos : int
        Current parsing posistion, offset from beginning of expression in
        characters
    lineno : int
        Current line number in the expression
    posInLine : int
        Parsing posistion in current line, 0-based
    """

    def __init__(self, expression, token, pos, lineno):
        self.expression = expression
        self.token = token
        self.pos = pos
        self.lineno = lineno
        self.posInLine = self._posInLine()
        msg = "Syntax error at or near '{0}' (line: {1}, pos: {2})"
        msg = msg.format(token, lineno, self.posInLine + 1)
        ParserYaccError.__init__(self, msg)

    def _posInLine(self):
        """Return position in current line"""
        lines = self.expression.split('\n')
        pos = self.pos
        for line in lines[:self.lineno - 1]:
            # +1 for newline
            pos -= len(line) + 1
        return pos


class ParserEOFError(ParserYaccError):
    """Exception raised for EOF-during-parser.
    """

    def __init__(self):
        Exception.__init__(self,
                           "End of input reached while expecting further input")


class ParserYacc:
    """Class which defines PLY grammar.
    """

    def __init__(self, **kwargs):

        kw = dict(write_tables=0, debug=False)
        kw.update(kwargs)

        self.parser = yacc.yacc(module=self, **kw)

    def parse(self, input, lexer=None, debug=False, tracking=False):
        """Parse input expression ad return parsed tree object.

        This is a trivial wrapper for yacc.LRParser.parse method which
        provides lexer if not given in arguments.

        Parameters
        ----------
        input : str
            Expression to parse
        lexer : object, optional
            Lexer instance, if not given then ParserLex.make_lexer() is
            called to create one.
        debug : bool, optional
            Set to True for debugging output.
        tracking : bool, optional
            Set to True for tracking line numbers in parser.
        """
        # make lexer
        if lexer is None:
            lexer = ParserLex.make_lexer()
        tree = self.parser.parse(input=input, lexer=lexer, debug=debug,
                                 tracking=tracking)
        return tree

    tokens = ParserLex.tokens[:]

    precedence = (
        ('left', 'OR'),
        ('left', 'AND'),
        ('nonassoc', 'EQ', 'NE'),  # Nonassociative operators
        ('nonassoc', 'LT', 'LE', 'GT', 'GE'),  # Nonassociative operators
        ('left', 'ADD', 'SUB'),
        ('left', 'MUL', 'DIV', 'MOD'),
        ('right', 'UPLUS', 'UMINUS', 'NOT'),  # unary plus and minus
    )

    # this is the starting rule
    def p_input(self, p):
        """ input : expr
                  | empty
        """
        p[0] = p[1]

    def p_empty(self, p):
        """ empty :
        """
        p[0] = None

    def p_expr(self, p):
        """ expr : expr OR expr
                 | expr AND expr
                 | NOT expr
                 | bool_primary
        """
        if len(p) == 4:
            p[0] = BinaryOp(lhs=p[1], op=p[2].upper(), rhs=p[3])
        elif len(p) == 3:
            p[0] = UnaryOp(op=p[1].upper(), operand=p[2])
        else:
            p[0] = p[1]

    def p_bool_primary(self, p):
        """ bool_primary : bool_primary EQ predicate
                         | bool_primary NE predicate
                         | bool_primary LT predicate
                         | bool_primary LE predicate
                         | bool_primary GE predicate
                         | bool_primary GT predicate
                         | predicate
        """
        if len(p) == 2:
            p[0] = p[1]
        else:
            p[0] = BinaryOp(lhs=p[1], op=p[2], rhs=p[3])

    def p_predicate(self, p):
        """ predicate : bit_expr IN LPAREN literal_list RPAREN
                      | bit_expr NOT IN LPAREN literal_list RPAREN
                      | bit_expr
        """
        if len(p) == 6:
            p[0] = IsIn(lhs=p[1], values=p[4])
        elif len(p) == 7:
            p[0] = IsIn(lhs=p[1], values=p[5], not_in=True)
        else:
            p[0] = p[1]

    def p_literal_list(self, p):
        """ literal_list : literal_list COMMA literal
                         | literal
        """
        if len(p) == 2:
            p[0] = [p[1]]
        else:
            p[0] = p[1] + [p[3]]

    def p_bit_expr(self, p):
        """ bit_expr : bit_expr ADD bit_expr
                     | bit_expr SUB bit_expr
                     | bit_expr MUL bit_expr
                     | bit_expr DIV bit_expr
                     | bit_expr MOD bit_expr
                     | simple_expr
        """
        if len(p) == 2:
            p[0] = p[1]
        else:
            p[0] = BinaryOp(lhs=p[1], op=p[2], rhs=p[3])

    def p_simple_expr_lit(self, p):
        """ simple_expr : literal
        """
        p[0] = p[1]

    def p_simple_expr_id(self, p):
        """ simple_expr : IDENTIFIER
        """
        p[0] = Identifier(p[1])

    def p_simple_expr_unary(self, p):
        """ simple_expr : ADD simple_expr %prec UPLUS
                        | SUB simple_expr %prec UMINUS
        """
        p[0] = UnaryOp(op=p[1], operand=p[2])

    def p_simple_expr_paren(self, p):
        """ simple_expr : LPAREN expr RPAREN
        """
        p[0] = Parens(p[2])

    def p_literal_num(self, p):
        """ literal : NUMERIC_LITERAL
        """
        p[0] = NumericLiteral(p[1])

    def p_literal_str(self, p):
        """ literal : STRING_LITERAL
        """
        p[0] = StringLiteral(p[1])

    # ---------- end of all grammar rules ----------

    # Error rule for syntax errors
    def p_error(self, p):
        if p is None:
            raise ParserEOFError()
        else:
            raise ParseError(p.lexer.lexdata, p.value, p.lexpos, p.lineno)
